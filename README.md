# Testownik Core

A Django-based backend application for managing quizzes, grades, and user feedback in an educational context. The project integrates with USOS API for user authentication and provides a RESTful API interface.

## Features

- User authentication via USOS API
- Quiz management system
- Grade tracking and management
- Alert system for notifications
- Feedback collection and management
- RESTful API with JWT authentication
- API documentation using DRF Spectacular
- CORS support for frontend integration

## Tech Stack

- Python 3
- Django
- Django REST Framework
- PostgreSQL (production) / SQLite (development)
- JWT Authentication
- USOS API Integration
- Gunicorn (production server)
- WhiteNoise (static files)

## Prerequisites

- Python 3
- pip (Python package manager)
- PostgreSQL (for production)
- USOS API credentials

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd testownik_core
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following variables:
```env
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173
CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Database settings (for production)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# Email settings
EMAIL_HOST=your-smtp-server
EMAIL_USE_TLS=True
EMAIL_PORT=587
EMAIL_HOST_USER=your-email
EMAIL_HOST_PASSWORD=your-password
DEFAULT_FROM_EMAIL=Testownik Solvro <testownik@solvro.pl>
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Create a superuser (optional):
```bash
python manage.py createsuperuser
```

7. Run the development server:
```bash
python manage.py runserver
```

## Project Structure

- `alerts/` - Alert system for notifications
- `feedback/` - Feedback collection and management
- `grades/` - Grade tracking and management
- `quizzes/` - Quiz management system
- `users/` - User management and authentication
- `templates/` - HTML templates
- `testownik_core/` - Main project configuration

## API Documentation

The API documentation is available at `/api/schema/swagger-ui/` when running the server. It provides detailed information about all available endpoints, request/response formats, and authentication requirements.

## Development

- The project uses Django REST Framework for API development
- JWT authentication is implemented for secure API access
- CORS is configured to allow frontend integration
- Rate limiting is implemented for API protection

## Production Deployment

For production deployment:

1. Set `DEBUG=False` in your environment variables
2. Configure a proper database (PostgreSQL recommended)
3. Set up proper email settings
4. Configure proper CORS and CSRF settings
5. Use Gunicorn as the production server:
```bash
gunicorn testownik_core.wsgi:application
```

