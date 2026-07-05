# Deploy on Vercel with Aiven MySQL

This project is configured for Flask on Vercel and MySQL on Aiven.

## 1. Create the Aiven MySQL database

1. Create a MySQL service in Aiven.
2. Open the service connection details.
3. Copy the host, port, user, password, and database name.
4. Build your database URL:

```env
DATABASE_URL=mysql+pymysql://avnadmin:YOUR_PASSWORD@YOUR_HOST.aivencloud.com:YOUR_PORT/defaultdb?ssl=true
```

If Aiven gives you a URL like this, it is also accepted:

```env
mysql://avnadmin:YOUR_PASSWORD@YOUR_HOST.aivencloud.com:YOUR_PORT/defaultdb?ssl-mode=REQUIRED
```

The app converts it automatically for PyMySQL.

## 2. Deploy to Vercel

1. Push this repository to GitHub.
2. Import the GitHub repository in Vercel.
3. Keep the framework preset as Other.
4. Add the environment variables below.
5. Deploy.

Required Vercel environment variables:

```env
DATABASE_URL=mysql+pymysql://avnadmin:YOUR_PASSWORD@YOUR_HOST.aivencloud.com:YOUR_PORT/defaultdb?ssl=true
SECRET_KEY=use-a-long-random-secret
ENVIRONMENT=production
ADMIN_EMAIL=your-admin-email@example.com
SITE_URL=https://your-vercel-or-custom-domain.com
```

Optional environment variables:

```env
ADMIN_NAME=Ajay Prakash Pandey
ADMIN_PHONE=8881254553
ADMIN_GITHUB=https://github.com/Ajay-Prakash-Pandey
ADMIN_LINKEDIN=https://www.linkedin.com/in/ajayprakashpandey/
SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your-gmail-app-password
WHATSAPP_MESSAGE_PREFIX=Hello! I got your message and will reply soon.
```

## 3. Files used for deployment

- `vercel.json` routes all requests to the Flask serverless entrypoint.
- `api/index.py` imports the Flask `app` from `main.py`.
- `requirements.txt` contains the Python packages Vercel installs.
- `.vercelignore` keeps local-only files out of the deployment.

Render-specific files have been removed.
