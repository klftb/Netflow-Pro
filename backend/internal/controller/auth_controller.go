package controller

import (
	"net/http"

	"flow-analytics-backend/internal/auth"
	"flow-analytics-backend/internal/model"

	"github.com/gin-gonic/gin"
)

type AuthController struct {
	authService *auth.AuthService
}

func NewAuthController(authService *auth.AuthService) *AuthController {
	return &AuthController{
		authService: authService,
	}
}

// RegisterRoutes registers auth API routes
func (ctrl *AuthController) RegisterRoutes(r *gin.Engine) {
	authGroup := r.Group("/api/v1/auth")
	{
		authGroup.POST("/login", ctrl.Login)
		authGroup.GET("/me", ctrl.GetMe)
		authGroup.POST("/change-password", ctrl.ChangePassword)
	}
}

// Login handles POST /api/v1/auth/login
func (ctrl *AuthController) Login(c *gin.Context) {
	var req model.LoginReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code":    400,
			"message": "请求参数不合法: 用户名与密码必填",
		})
		return
	}

	resp, err := ctrl.authService.Login(c.Request.Context(), req.Username, req.Password)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"code":    401,
			"message": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code":    0,
		"message": "登录成功",
		"data":    resp,
	})
}

// GetMe handles GET /api/v1/auth/me
func (ctrl *AuthController) GetMe(c *gin.Context) {
	usernameVal, exists := c.Get("username")
	if !exists {
		c.JSON(http.StatusUnauthorized, gin.H{"code": 401, "message": "未登录"})
		return
	}
	username := usernameVal.(string)

	u, err := ctrl.authService.GetUser(c.Request.Context(), username)
	if err != nil || u == nil {
		displayName, _ := c.Get("display_name")
		role, _ := c.Get("role")
		authType, _ := c.Get("auth_type")
		c.JSON(http.StatusOK, gin.H{
			"code": 0,
			"data": gin.H{
				"username":     username,
				"display_name": displayName,
				"role":         role,
				"auth_type":    authType,
			},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 0,
		"data": u,
	})
}

// ChangePassword handles POST /api/v1/auth/change-password
func (ctrl *AuthController) ChangePassword(c *gin.Context) {
	usernameVal, exists := c.Get("username")
	if !exists {
		c.JSON(http.StatusUnauthorized, gin.H{"code": 401, "message": "未登录"})
		return
	}
	username := usernameVal.(string)

	var req model.ChangePasswordReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code":    400,
			"message": "参数错误：需提供旧密码与新密码",
		})
		return
	}

	if err := ctrl.authService.ChangePassword(c.Request.Context(), username, req.OldPassword, req.NewPassword); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code":    4001,
			"message": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code":    0,
		"message": "密码修改成功，请牢记您的新密码",
	})
}
