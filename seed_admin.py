import os
import sys

# Import app context and models from the project
try:
    from main import app, db, User, bcrypt, ADMIN_EMAIL
except Exception as e:
    print('Failed to import application:', e)
    sys.exit(1)


def create_or_update_admin(username: str, email: str, password: str) -> None:
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        if user:
            user.email = email
            user.password = hashed
            db.session.commit()
            print(f"Updated admin user: {username}")
        else:
            user = User(username=username, email=email, password=hashed)
            db.session.add(user)
            db.session.commit()
            print(f"Created admin user: {username}")


def main():
    username = os.environ.get('ADMIN_USERNAME') or input('Admin username: ')
    email = os.environ.get('ADMIN_EMAIL') or ADMIN_EMAIL or input('Admin email: ')
    password = os.environ.get('ADMIN_PASSWORD') or input('Admin password: ')

    if not username or not email or not password:
        print('Username, email and password are required')
        sys.exit(1)

    create_or_update_admin(username, email, password)


if __name__ == '__main__':
    main()
