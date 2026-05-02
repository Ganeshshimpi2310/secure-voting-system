# Secure Vote System

A modern, secure voting system built with Flask, SQLAlchemy, and Flask-Login.

## Features

- User registration and authentication
- Secure voting with one vote per user
- Real-time results
- Admin panel for managing candidates and viewing results
- File uploads for candidate photos and logos
- CSRF protection
- Email contact form
- CSV export of results

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python app.py
   ```

3. Open http://localhost:5000 in your browser.

## Docker

Build and run with Docker:
```bash
docker build -t voting-system .
docker run -p 5000:5000 voting-system
```

## Environment Variables

- `SECRET_KEY`: Secret key for Flask sessions (auto-generated if not set)

## Admin Access

Register a user with username "admin" to gain admin privileges.

## Security

- Password hashing with SHA-256
- CSRF protection
- Secure file uploads
- SQLAlchemy ORM for database interactions