package auth

import (
	"errors"
	"time"

	"flow-analytics-backend/internal/model"

	"github.com/golang-jwt/jwt/v5"
)

var (
	// JwtSecret can be overridden or randomized
	jwtSecret = []byte("netflow-pro-secure-auth-jwt-token-secret-key-2026")
)

type CustomClaims struct {
	Username    string `json:"username"`
	DisplayName string `json:"display_name"`
	Role        string `json:"role"`
	AuthType    string `json:"auth_type"`
	jwt.RegisteredClaims
}

// GenerateToken generates a JWT token for a user with 24 hours validity
func GenerateToken(user *model.SystemUser) (string, int64, error) {
	expireTime := time.Now().Add(24 * time.Hour)
	claims := CustomClaims{
		Username:    user.Username,
		DisplayName: user.DisplayName,
		Role:        user.Role,
		AuthType:    user.AuthType,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(expireTime),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			Issuer:    "NetFlow-Pro",
			Subject:   user.Username,
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		return "", 0, err
	}
	return tokenString, expireTime.Unix(), nil
}

// ValidateToken parses and validates a JWT token string
func ValidateToken(tokenString string) (*CustomClaims, error) {
	token, err := jwt.ParseWithClaims(tokenString, &CustomClaims{}, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return jwtSecret, nil
	})

	if err != nil {
		return nil, err
	}

	if claims, ok := token.Claims.(*CustomClaims); ok && token.Valid {
		return claims, nil
	}

	return nil, errors.New("invalid token")
}
