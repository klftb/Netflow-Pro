package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"flow-analytics-backend/internal/alert"
	"flow-analytics-backend/internal/auth"
	"flow-analytics-backend/internal/controller"
	"flow-analytics-backend/internal/librenms"
	"flow-analytics-backend/internal/middleware"
	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/netbox"
	"flow-analytics-backend/internal/repository"
	"flow-analytics-backend/internal/syncer"
	"flow-analytics-backend/internal/system"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	port := flag.String("port", "8080", "HTTP Server Port")
	chAddr := flag.String("ch-addr", "127.0.0.1:9000", "ClickHouse Native Address")
	chDB := flag.String("ch-db", "ntopng", "ClickHouse Database")
	chUser := flag.String("ch-user", "default", "ClickHouse Username")
	chPass := flag.String("ch-pass", "", "ClickHouse Password")
	flag.Parse()

	if envPort := os.Getenv("PORT"); envPort != "" {
		*port = envPort
	}
	if envAddr := os.Getenv("CLICKHOUSE_ADDR"); envAddr != "" {
		*chAddr = envAddr
	}

	log.Printf("[*] Starting Flow Analytics API Server on :%s", *port)
	log.Printf("[*] Connecting to ClickHouse at %s (DB: %s)", *chAddr, *chDB)

	repo, err := repository.NewClickHouseRepo(*chAddr, *chDB, *chUser, *chPass)
	if err != nil {
		log.Fatalf("[FATAL] ClickHouse initialization failed: %v", err)
	}

	// Ensure configuration tables exist
	initCtx, initCancel := context.WithTimeout(context.Background(), 5*time.Second)
	if err := repo.EnsureConfigTables(initCtx); err != nil {
		log.Printf("[WARN] Failed to ensure config tables: %v", err)
	}
	initCancel()

	// Initialize and Start NBA Alert Engine
	alertFile := "/opt/flow-backend/alert_output.json"
	if _, err := os.Stat("/opt/flow-backend"); os.IsNotExist(err) {
		alertFile = "alert_output.json"
	}
	alertEngine := alert.NewEngine(repo.GetConn(), alertFile)
	alertEngine.Start()

	gin.SetMode(gin.ReleaseMode)
	r := gin.Default()

	// Enable CORS for frontend console
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
	}))

	// Enforce JWT Authentication for API endpoints
	r.Use(middleware.JWTAuthMiddleware())

	sysConfigs, _ := repo.GetSystemConfigs(context.Background())
	libreURL := sysConfigs["librenms_url"]
	if libreURL == "" {
		libreURL = os.Getenv("LIBRENMS_URL")
		if libreURL == "" {
			libreURL = "http://librenms.example.com/api/v0"
		}
	}
	libreToken := sysConfigs["librenms_token"]
	if libreToken == "" {
		libreToken = os.Getenv("LIBRENMS_TOKEN")
		if libreToken == "" {
			libreToken = ""
		}
	}
	netboxURL := sysConfigs["netbox_url"]
	if netboxURL == "" {
		netboxURL = os.Getenv("NETBOX_URL")
		if netboxURL == "" {
			netboxURL = "http://netbox.example.com/api/"
		}
	}
	netboxToken := sysConfigs["netbox_token"]
	if netboxToken == "" {
		netboxToken = os.Getenv("NETBOX_TOKEN")
		if netboxToken == "" {
			netboxToken = ""
		}
	}

	libreClient := librenms.NewClient(libreURL, libreToken)
	log.Printf("[*] LibreNMS Integration initialized: %s", libreURL)

	netboxClient := netbox.NewClient(netboxURL, netboxToken)
	log.Printf("[*] NetBox Integration initialized: %s", netboxURL)

	// Initialize LDAP Client
	ldapClient := auth.NewLDAPClient(&model.LdapSettings{
		Enabled:      sysConfigs["ldap_enabled"] == "true",
		URL:          sysConfigs["ldap_url"],
		BaseDN:       sysConfigs["ldap_base_dn"],
		BindDN:       sysConfigs["ldap_bind_dn"],
		BindPassword: sysConfigs["ldap_bind_password"],
		UserFilter:   sysConfigs["ldap_user_filter"],
		DefaultRole:  sysConfigs["ldap_default_role"],
	})
	log.Printf("[*] LDAP Integration initialized: enabled=%v, url=%s", sysConfigs["ldap_enabled"] == "true", sysConfigs["ldap_url"])

	// Initialize Auth Service & Controller
	authService := auth.NewAuthService(repo, ldapClient)
	authCtrl := controller.NewAuthController(authService)
	authCtrl.RegisterRoutes(r)

	// Initialize IPResolver & NetBox Syncer
	ipResolver := repository.NewIPResolver()
	netboxSyncer := syncer.NewNetboxSyncer(repo, netboxClient, ipResolver)
	netboxSyncer.Start(context.Background())

	// Initialize and Start Auto-Discovery and LibreNMS Syncer Engine (scans every 30s)
	syncerEngine := syncer.NewAutoDiscoverSyncer(repo, libreClient, 30*time.Second)
	syncerEngine.Start()

	trafficCtrl := controller.NewTrafficController(repo, alertEngine, libreClient, syncerEngine, netboxClient, ipResolver)
	trafficCtrl.RegisterRoutes(r)

	// Initialize System Manager (services status, restart, one-click inspection)
	sysMgr := system.NewManager(repo, libreClient, netboxClient, ldapClient)

	configCtrl := controller.NewConfigController(repo, alertEngine, libreClient, syncerEngine, netboxClient, ldapClient, netboxSyncer, ipResolver, sysMgr)
	configCtrl.RegisterRoutes(r)

	// Serve Frontend Dashboard with No-Cache header for index.html
	serveIndex := func(filePath string) gin.HandlerFunc {
		return func(c *gin.Context) {
			c.Header("Cache-Control", "no-cache, no-store, must-revalidate")
			c.Header("Pragma", "no-cache")
			c.Header("Expires", "0")
			c.File(filePath)
		}
	}

	indexPath := "frontend/index.html"
	staticDir := "frontend"
	if _, err := os.Stat(indexPath); err != nil {
		indexPath = "/opt/flow-backend/frontend/index.html"
		staticDir = "/opt/flow-backend/frontend"
	}
	r.GET("/", serveIndex(indexPath))
	r.HEAD("/", serveIndex(indexPath))
	r.Static("/frontend", staticDir)

	addr := fmt.Sprintf("0.0.0.0:%s", *port)
	log.Printf("[+] RESTful API listening on http://%s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("[FATAL] Failed to start HTTP server: %v", err)
	}
}
