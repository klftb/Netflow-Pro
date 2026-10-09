package middleware

import (
	"net/http"
	"strings"

	"flow-analytics-backend/internal/auth"

	"github.com/gin-gonic/gin"
)

// JWTAuthMiddleware enforces JWT token verification on protected routes
func JWTAuthMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Whitelist public endpoints and static frontend assets
		path := c.Request.URL.Path
		if !strings.HasPrefix(path, "/api/") ||
			strings.HasPrefix(path, "/api/v1/auth/login") ||
			strings.HasPrefix(path, "/api/v1/health") ||
			c.Request.Method == http.MethodOptions {
			c.Next()
			return
		}

		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":    401,
				"message": "未提供身份认证凭据，请先登录系统",
			})
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":    401,
				"message": "身份认证令牌格式不合法 (需为 Bearer <token>)",
			})
			return
		}

		tokenString := strings.TrimSpace(parts[1])
		claims, err := auth.ValidateToken(tokenString)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":    401,
				"message": "登录会话已过期或令牌无效，请重新登录",
				"error":   err.Error(),
			})
			return
		}

		// Inject user context
		c.Set("username", claims.Username)
		c.Set("display_name", claims.DisplayName)
		c.Set("role", claims.Role)
		c.Set("auth_type", claims.AuthType)

		c.Next()
	}
}

// RequireAdmin ensures the authenticated user has 'admin' privileges
func RequireAdmin() gin.HandlerFunc {
	return func(c *gin.Context) {
		role, exists := c.Get("role")
		if !exists || role != "admin" {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"code":    403,
				"message": "权限不足：该操作仅限系统管理员 (Admin) 执行",
			})
			return
		}
		c.Next()
	}
}
