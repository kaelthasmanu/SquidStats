from flask import Flask, render_template
import socket
from parsers.connections import parse_raw_data, group_by_user
from services.fetch_data import fetch_squid_data
from parsers.cache import fetch_squid_cache_stats

app = Flask(__name__, static_folder='./static')

@app.route('/')
def index():
    """
    Main page showing Squid statistics grouped by users.
    """
    raw_data = fetch_squid_data()
    if 'Error' in raw_data:
        return f"Error al conectar con Squid: {raw_data}"

    connections = parse_raw_data(raw_data)
    grouped_connections = group_by_user(connections)

    return render_template('index.html', grouped_connections=grouped_connections)

@app.route('/stats')
def cache_stats():
    data = fetch_squid_cache_stats()
    stats_data = vars(data) if hasattr(data, '__dict__') else data
    print(data)
    return render_template('cacheView.html', cache_stats=stats_data)

@app.route('/logs')
def logs():

    return render_template('logsView.html')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
