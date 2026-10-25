# Инфраструктура сервера

- **Хост:** VPS в Швеции
- **IP-адрес:** `89.169.34.105`
- **ОС:** Ubuntu 24.04 LTS
- **Домены:** `gorky.bond`, `www.gorky.bond`
- **Безопасность:** UFW фаервол (открыты только порты 22/SSH, 80/HTTP, 443/HTTPS)
- **SSL-сертификат:** Let's Encrypt (Certbot), настроен авторедирект на HTTPS и автоматическое продление
- **Окружение:** Docker Engine, Docker Compose v2, Nginx
- **Доступность API:** OpenAI, Anthropic, Google Gemini доступны напрямую без блокировок