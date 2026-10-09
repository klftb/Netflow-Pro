package controller

import (
	"net/http"
	"strings"

	"flow-analytics-backend/internal/alert"
	"flow-analytics-backend/internal/librenms"
	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/netbox"
	"flow-analytics-backend/internal/repository"
	"flow-analytics-backend/internal/syncer"

	"github.com/gin-gonic/gin"
)

type TrafficController struct {
	repo         *repository.ClickHouseRepo
	alertEngine  *alert.Engine
	libreClient  *librenms.Client
	netboxClient *netbox.Client
	syncer       *syncer.AutoDiscoverSyncer
	resolver     *repository.IPResolver
}

func NewTrafficController(repo *repository.ClickHouseRepo, alertEngine *alert.Engine, libreClient *librenms.Client, syncer *syncer.AutoDiscoverSyncer, netboxClient *netbox.Client, resolver *repository.IPResolver) *TrafficController {
	return &TrafficController{repo: repo, alertEngine: alertEngine, libreClient: libreClient, syncer: syncer, netboxClient: netboxClient, resolver: resolver}
}

func (c *TrafficController) RegisterRoutes(r *gin.Engine) {
	v1 := r.Group("/api/v1")
	{
		v1.GET("/health", c.HealthCheck)
		v1.GET("/alerts", c.GetAlerts)
		v1.GET("/devices/overview", c.GetDeviceOverview)
		traffic := v1.Group("/traffic")
		{
			traffic.POST("/trend", c.GetTrafficTrend)
			traffic.POST("/topn", c.GetTopN)
			traffic.POST("/sankey", c.GetSankey)
			traffic.POST("/sessions", c.GetInterfaceSessions)
		}
	}
}

func (c *TrafficController) GetAlerts(ctx *gin.Context) {
	if c.alertEngine == nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: []interface{}{}})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    c.alertEngine.GetAlerts(),
	})
}

func (c *TrafficController) HealthCheck(ctx *gin.Context) {
	if err := c.repo.Ping(ctx.Request.Context()); err != nil {
		ctx.JSON(http.StatusServiceUnavailable, model.ResponseEnvelope{
			Code:    5003,
			Message: "ClickHouse connectivity failed: " + err.Error(),
			Data:    nil,
		})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "System operational. ClickHouse and Ingestion pipeline active.",
		Data: gin.H{
			"status": "healthy",
			"engine": "Akvorado-ClickHouse-Go",
		},
	})
}

func (c *TrafficController) GetTrafficTrend(ctx *gin.Context) {
	var req model.TrendRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{
			Code:    4001,
			Message: "Invalid request payload: " + err.Error(),
			Data:    nil,
		})
		return
	}

	resp, err := c.repo.QueryTrafficTrend(ctx.Request.Context(), req)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{
			Code:    5001,
			Message: "Trend query failed: " + err.Error(),
			Data:    nil,
		})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    resp,
	})
}

func (c *TrafficController) GetTopN(ctx *gin.Context) {
	var req model.TopNRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{
			Code:    4001,
			Message: "Invalid request payload: " + err.Error(),
			Data:    nil,
		})
		return
	}

	resp, err := c.repo.QueryTopN(ctx.Request.Context(), req)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{
			Code:    5002,
			Message: "TopN query failed: " + err.Error(),
			Data:    nil,
		})
		return
	}

	// Enrich with hostnames (Priority 1: NetBox DNS/Host, Priority 2: Local Host/Subnet, Fallback: IP)
	if c.resolver != nil && resp != nil && len(resp.Items) > 0 && (req.Dimension == "ip" || req.Dimension == "") {
		for i := range resp.Items {
			ip := resp.Items[i].Key
			if ip != "" {
				displayName, matchedName, _ := c.resolver.Resolve(ip)
				if matchedName != "" {
					resp.Items[i].Hostname = matchedName
					resp.Items[i].Label = displayName
				}
			}
		}
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    resp,
	})
}

func (c *TrafficController) GetSankey(ctx *gin.Context) {
	var req model.SankeyRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{
			Code:    4001,
			Message: "Invalid request payload: " + err.Error(),
			Data:    nil,
		})
		return
	}

	resp, err := c.repo.QuerySankey(ctx.Request.Context(), req)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{
			Code:    5003,
			Message: "Sankey query failed: " + err.Error(),
			Data:    nil,
		})
		return
	}

	// Enrich with hostnames (Priority 1: NetBox DNS/Host, Priority 2: Local Host/Subnet, Fallback: IP)
	if c.resolver != nil && resp != nil && len(resp.Nodes) > 0 {
		renameMap := make(map[string]string)
		for _, node := range resp.Nodes {
			if strings.HasPrefix(node.Name, "源: ") {
				ip := strings.TrimPrefix(node.Name, "源: ")
				displayName, matchedName, _ := c.resolver.Resolve(ip)
				if matchedName != "" {
					renameMap[node.Name] = "源: " + displayName
				}
			} else if strings.HasPrefix(node.Name, "目: ") {
				ip := strings.TrimPrefix(node.Name, "目: ")
				displayName, matchedName, _ := c.resolver.Resolve(ip)
				if matchedName != "" {
					renameMap[node.Name] = "目: " + displayName
				}
			}
		}
		if len(renameMap) > 0 {
			for i := range resp.Nodes {
				if newName, ok := renameMap[resp.Nodes[i].Name]; ok {
					resp.Nodes[i].Name = newName
				}
			}
			for i := range resp.Links {
				if newSrc, ok := renameMap[resp.Links[i].Source]; ok {
					resp.Links[i].Source = newSrc
				}
				if newDst, ok := renameMap[resp.Links[i].Target]; ok {
					resp.Links[i].Target = newDst
				}
			}
		}
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    resp,
	})
}

func (c *TrafficController) GetDeviceOverview(ctx *gin.Context) {
	devices, err := c.repo.QueryDeviceOverview(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{
			Code:    5004,
			Message: "Failed to query devices overview: " + err.Error(),
			Data:    nil,
		})
		return
	}

	// Enrich with LibreNMS real-time polled interface rates if available
	if c.libreClient != nil {
		for i := range devices {
			dev := &devices[i]
			ports, err := c.libreClient.GetDevicePorts(ctx.Request.Context(), dev.ExporterIP)
			if err == nil && len(ports) > 0 {
				portRateMap := make(map[uint32]librenms.LibrePort)
				for _, p := range ports {
					portRateMap[p.IfIndex] = p
				}
				var libreRxTotal, libreTxTotal float64
				var hasLibreTraffic bool
				for j := range dev.Interfaces {
					ifc := &dev.Interfaces[j]
					if lp, ok := portRateMap[ifc.IfIndex]; ok {
						ifc.LibreInBps = lp.IfInOctetsRate * 8.0
						ifc.LibreOutBps = lp.IfOutOctetsRate * 8.0
						if ifc.LibreInBps > 0 || ifc.LibreOutBps > 0 {
							hasLibreTraffic = true
							ifc.RxBps = ifc.LibreInBps
							ifc.TxBps = ifc.LibreOutBps
							libreRxTotal += ifc.LibreInBps
							libreTxTotal += ifc.LibreOutBps
						}
					}
				}
				if hasLibreTraffic {
					dev.TotalRxBps = libreRxTotal
					dev.TotalTxBps = libreTxTotal
				}
			}
		}
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    devices,
	})
}

func (c *TrafficController) GetInterfaceSessions(ctx *gin.Context) {
	var req model.SessionRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{
			Code:    4001,
			Message: "Invalid request payload: " + err.Error(),
			Data:    nil,
		})
		return
	}

	resp, err := c.repo.QueryInterfaceSessions(ctx.Request.Context(), req)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{
			Code:    5005,
			Message: "Failed to query interface sessions: " + err.Error(),
			Data:    nil,
		})
		return
	}

	// Enrich with hostnames (Priority 1: NetBox DNS/Host, Priority 2: Local Host/Subnet, Fallback: IP)
	if c.resolver != nil && resp != nil && len(resp.Items) > 0 {
		for i := range resp.Items {
			if resp.Items[i].SrcIP != "" {
				_, matchedName, _ := c.resolver.Resolve(resp.Items[i].SrcIP)
				if matchedName != "" {
					resp.Items[i].SrcHostname = matchedName
				}
			}
			if resp.Items[i].DstIP != "" {
				_, matchedName, _ := c.resolver.Resolve(resp.Items[i].DstIP)
				if matchedName != "" {
					resp.Items[i].DstHostname = matchedName
				}
			}
		}
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data:    resp,
	})
}

