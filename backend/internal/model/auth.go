package model

import "time"

// SystemUser represents a user account
type SystemUser struct {
	Username     string    `json:"username"`
	PasswordHash string    `json:"-"`
	DisplayName  string    `json:"display_name"`
	Role         string    `json:"role"`      // 'admin', 'viewer'
	AuthType     string    `json:"auth_type"` // 'local', 'ldap'
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

// LoginReq represents login request payload
type LoginReq struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// LoginResp represents login response with token and user profile
type LoginResp struct {
	Token       string      `json:"token"`
	ExpiresAt   int64       `json:"expires_at"`
	User        *SystemUser `json:"user"`
	RequirePass bool        `json:"require_change_password,omitempty"`
}

// ChangePasswordReq represents password change payload
type ChangePasswordReq struct {
	OldPassword string `json:"old_password" binding:"required"`
	NewPassword string `json:"new_password" binding:"required"`
}

// LdapSettings represents LDAP/AD configuration
type LdapSettings struct {
	Enabled       bool   `json:"enabled"`
	URL           string `json:"url"`
	BaseDN        string `json:"base_dn"`
	BindDN        string `json:"bind_dn"`
	BindPassword  string `json:"bind_password"`
	UserFilter    string `json:"user_filter"`
	DefaultRole   string `json:"default_role"`
}

// LdapTestReq represents request to test LDAP connectivity
type LdapTestReq struct {
	URL          string `json:"url"`
	BaseDN       string `json:"base_dn"`
	BindDN       string `json:"bind_dn"`
	BindPassword string `json:"bind_password"`
	UserFilter   string `json:"user_filter"`
}
