package auth

import (
	"context"
	"errors"
	"fmt"
	"log"

	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/repository"

	"golang.org/x/crypto/bcrypt"
)

type AuthService struct {
	repo       *repository.ClickHouseRepo
	ldapClient *LDAPClient
}

func NewAuthService(repo *repository.ClickHouseRepo, ldapClient *LDAPClient) *AuthService {
	return &AuthService{
		repo:       repo,
		ldapClient: ldapClient,
	}
}

// Login performs hybrid authentication (Local First -> LDAP Fallback)
func (s *AuthService) Login(ctx context.Context, username, password string) (*model.LoginResp, error) {
	if username == "" || password == "" {
		return nil, errors.New("用户名与密码不能为空")
	}

	// 1. Try local user database
	localUser, err := s.repo.GetUser(ctx, username)
	if err == nil && localUser != nil && localUser.AuthType == "local" {
		if err := bcrypt.CompareHashAndPassword([]byte(localUser.PasswordHash), []byte(password)); err == nil {
			token, exp, err := GenerateToken(localUser)
			if err != nil {
				return nil, fmt.Errorf("签发登录令牌失败: %v", err)
			}
			log.Printf("[+] Local user login successful: %s (%s)", localUser.Username, localUser.Role)
			return &model.LoginResp{
				Token:     token,
				ExpiresAt: exp,
				User:      localUser,
			}, nil
		}
	}

	// 2. If local fails or not exists, try LDAP / Active Directory
	if s.ldapClient != nil && s.ldapClient.IsEnabled() {
		ldapUser, err := s.ldapClient.Authenticate(username, password)
		if err == nil && ldapUser != nil {
			// Issue JWT
			token, exp, err := GenerateToken(ldapUser)
			if err != nil {
				return nil, fmt.Errorf("签发 LDAP 令牌失败: %v", err)
			}
			// Sync LDAP user into local DB for record
			_ = s.repo.SaveUser(ctx, ldapUser)

			return &model.LoginResp{
				Token:     token,
				ExpiresAt: exp,
				User:      ldapUser,
			}, nil
		}
	}

	return nil, errors.New("用户名或密码错误")
}

// ChangePassword changes password for a local user
func (s *AuthService) ChangePassword(ctx context.Context, username, oldPassword, newPassword string) error {
	if len(newPassword) < 6 {
		return errors.New("新密码长度不能少于 6 位")
	}

	user, err := s.repo.GetUser(ctx, username)
	if err != nil || user == nil {
		return errors.New("用户不存在")
	}
	if user.AuthType != "local" {
		return errors.New("域用户无法在本地修改密码，请联系网络域管理员")
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(oldPassword)); err != nil {
		return errors.New("旧密码输入错误")
	}

	hashed, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return fmt.Errorf("密码加密异常: %v", err)
	}

	return s.repo.UpdateUserPassword(ctx, username, string(hashed))
}

// GetUser fetches current user profile
func (s *AuthService) GetUser(ctx context.Context, username string) (*model.SystemUser, error) {
	return s.repo.GetUser(ctx, username)
}
