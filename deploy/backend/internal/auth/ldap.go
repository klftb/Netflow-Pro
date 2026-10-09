package auth

import (
	"crypto/tls"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"flow-analytics-backend/internal/model"

	"github.com/go-ldap/ldap/v3"
)

type LDAPClient struct {
	mu           sync.RWMutex
	enabled      bool
	url          string
	baseDN       string
	bindDN       string
	bindPassword string
	userFilter   string
	defaultRole  string
}

func NewLDAPClient(cfg *model.LdapSettings) *LDAPClient {
	c := &LDAPClient{}
	if cfg != nil {
		c.UpdateConfig(cfg)
	}
	return c
}

// UpdateConfig updates LDAP configurations safely at runtime
func (c *LDAPClient) UpdateConfig(cfg *model.LdapSettings) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.enabled = cfg.Enabled
	c.url = strings.TrimSpace(cfg.URL)
	c.baseDN = strings.TrimSpace(cfg.BaseDN)
	c.bindDN = strings.TrimSpace(cfg.BindDN)
	c.bindPassword = cfg.BindPassword
	c.userFilter = strings.TrimSpace(cfg.UserFilter)
	if c.userFilter == "" {
		c.userFilter = "(&(objectClass=user)(sAMAccountName=%s))"
	}
	c.defaultRole = strings.TrimSpace(cfg.DefaultRole)
	if c.defaultRole == "" {
		c.defaultRole = "admin"
	}
	log.Printf("[*] LDAP Client configuration updated: enabled=%v, url=%s, baseDN=%s", c.enabled, c.url, c.baseDN)
}

// IsEnabled checks if LDAP authentication is enabled
func (c *LDAPClient) IsEnabled() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.enabled && c.url != ""
}

// GetConfig returns current LDAP configurations
func (c *LDAPClient) GetConfig() model.LdapSettings {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return model.LdapSettings{
		Enabled:      c.enabled,
		URL:          c.url,
		BaseDN:       c.baseDN,
		BindDN:       c.bindDN,
		BindPassword: c.bindPassword,
		UserFilter:   c.userFilter,
		DefaultRole:  c.defaultRole,
	}
}

// dialLDAP creates connection with TLS skip verify if ldaps
func dialLDAP(ldapURL string, timeout time.Duration) (*ldap.Conn, error) {
	tlsConfig := &tls.Config{InsecureSkipVerify: true}
	conn, err := ldap.DialURL(ldapURL, ldap.DialWithTLSConfig(tlsConfig))
	if err != nil {
		return nil, err
	}
	conn.SetTimeout(timeout)
	return conn, nil
}

// TestConnection tests connectivity and credentials to LDAP server
func (c *LDAPClient) TestConnection(req *model.LdapTestReq) (int64, string, error) {
	t0 := time.Now()
	timeout := 5 * time.Second

	url := strings.TrimSpace(req.URL)
	if url == "" {
		return 0, "", fmt.Errorf("LDAP 服务器地址不能为空")
	}

	conn, err := dialLDAP(url, timeout)
	if err != nil {
		return 0, "", fmt.Errorf("无法连接至 LDAP 服务器: %v", err)
	}
	defer conn.Close()

	// If bind DN specified, test binding
	if req.BindDN != "" {
		if err := conn.Bind(req.BindDN, req.BindPassword); err != nil {
			return 0, "", fmt.Errorf("LDAP 代理账号 Bind 认证失败: %v", err)
		}
	}

	// If base DN specified, test a lightweight search
	var msg string
	if req.BaseDN != "" {
		searchReq := ldap.NewSearchRequest(
			req.BaseDN,
			ldap.ScopeBaseObject,
			ldap.NeverDerefAliases,
			0,
			3,
			false,
			"(objectClass=*)",
			[]string{"namingContexts", "defaultNamingContext"},
			nil,
		)
		_, err := conn.Search(searchReq)
		if err != nil {
			msg = fmt.Sprintf("LDAP 连通成功 (Base DN 搜索告警: %v)", err)
		} else {
			msg = "LDAP / Active Directory 连接与目录探测成功！"
		}
	} else {
		msg = "LDAP 连接成功 (未指定 Base DN)"
	}

	latency := time.Since(t0).Milliseconds()
	return latency, msg, nil
}

// Authenticate verifies user credentials via LDAP
func (c *LDAPClient) Authenticate(username, password string) (*model.SystemUser, error) {
	c.mu.RLock()
	enabled := c.enabled
	url := c.url
	baseDN := c.baseDN
	bindDN := c.bindDN
	bindPass := c.bindPassword
	filterTemplate := c.userFilter
	defaultRole := c.defaultRole
	c.mu.RUnlock()

	if !enabled || url == "" {
		return nil, fmt.Errorf("LDAP 认证未启用")
	}
	if password == "" {
		return nil, fmt.Errorf("密码不能为空")
	}

	timeout := 6 * time.Second
	conn, err := dialLDAP(url, timeout)
	if err != nil {
		return nil, fmt.Errorf("连接 LDAP 失败: %v", err)
	}
	defer conn.Close()

	var userDN string
	displayName := username

	// Mode 1: Search using Bind DN, then bind as user
	if bindDN != "" {
		if err := conn.Bind(bindDN, bindPass); err != nil {
			return nil, fmt.Errorf("LDAP 服务代理账户认证失败: %v", err)
		}

		filter := fmt.Sprintf(filterTemplate, ldap.EscapeFilter(username))
		searchReq := ldap.NewSearchRequest(
			baseDN,
			ldap.ScopeWholeSubtree,
			ldap.NeverDerefAliases,
			1,
			5,
			false,
			filter,
			[]string{"dn", "cn", "displayName", "mail", "sAMAccountName"},
			nil,
		)

		sr, err := conn.Search(searchReq)
		if err != nil {
			return nil, fmt.Errorf("搜索用户失败: %v", err)
		}
		if len(sr.Entries) == 0 {
			return nil, fmt.Errorf("未在目录中找到用户 %s", username)
		}

		entry := sr.Entries[0]
		userDN = entry.DN
		if dnName := entry.GetAttributeValue("displayName"); dnName != "" {
			displayName = dnName
		} else if cn := entry.GetAttributeValue("cn"); cn != "" {
			displayName = cn
		}
	} else {
		// Mode 2: Direct bind (e.g. user@domain or uid=username,baseDN)
		if strings.Contains(username, "@") || strings.Contains(username, "=") {
			userDN = username
		} else if baseDN != "" {
			userDN = fmt.Sprintf("uid=%s,%s", ldap.EscapeFilter(username), baseDN)
		} else {
			userDN = username
		}
	}

	// Rebind as user to verify password
	userConn, err := dialLDAP(url, timeout)
	if err != nil {
		return nil, fmt.Errorf("创建用户认证连接失败: %v", err)
	}
	defer userConn.Close()

	if err := userConn.Bind(userDN, password); err != nil {
		return nil, fmt.Errorf("LDAP 域账号密码错误")
	}

	log.Printf("[+] LDAP Authentication successful for user: %s (DN: %s)", username, userDN)

	return &model.SystemUser{
		Username:    username,
		DisplayName: displayName,
		Role:        defaultRole,
		AuthType:    "ldap",
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
	}, nil
}
