# Squid Log Parser Dashboard 🐙📊

A modern tool for parsing and analyzing Squid logs, providing a sleek and user-friendly dashboard to visualize real-time connection data. This project helps network administrators monitor and manage Squid proxy connections effectively.

---

![DEMO](https://github.com/kaelthasmanu/SquidStats/blob/main/assets/photo_2025-03-16_10-33-06.jpg "DEMO")


## 🌟 Features
- **Real-time Log Parsing**: Parses active Squid connections and displays detailed information.
- **User Monitoring**: Identifies connections by username, URI, and log type.
- **Metrics Overview**:
  - Total read and written data for each connection.
  - Number of requests per connection.
  - Delay pool usage.
- **Interactive Dashboard**: Clean interface for easy data interpretation.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Squid proxy server
- `squidclient` installed on the server

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/kaelthasmanu/SquidStats.git
   cd squid-log-parser-dashboard
   ```
2. Install requeriments python:
  ```bash
  pip install -r requirements.txt
  ```
3. Run App 🚀:
```bash
python app.py
```
4. With your preferred browser, visit the installation URL:
```bash
http://ip/hostname:5000
```

🕒 Run on System Startup
To ensure the application starts automatically when the system boots, add the following cron job:
1. Open with a editor the file crontab
```bash
nano /etc/crontab
```
2. Add the following line to the crontab file(change path_app for your path):
```bash
@reboot root nohup python3 path_app/app.py &
```
3. Save

## 🛠️ Technologies Used

  Backend: Python, Flask
  Frontend: HTML, CSS

## 🤝 Contributing
1. Fork the repository:
   ```bash
   git checkout -b feature-name
   ```
2.Create a new branch for your feature or fix:
 ```bash
 git checkout -b feature-name
 ```
3.Commit your changes and push the branch:
  ```bash
  git push origin feature-name
  ```
4.Open a pull request.

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.
