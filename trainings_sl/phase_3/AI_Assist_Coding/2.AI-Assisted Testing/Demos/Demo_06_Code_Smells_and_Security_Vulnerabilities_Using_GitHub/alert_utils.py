import sqlite3


def format_critical_alert_message(title, source, metric_name, metric_value, threshold):
    message = "CRITICAL ALERT: " + title + " from " + source + ". "
    message += metric_name + " reached " + str(metric_value)
    message += ", threshold is " + str(threshold) + "."
    if metric_value > threshold * 1.5:
        message += " This is over 150% of threshold -- page on-call immediately."
    return message


def format_warning_alert_message(title, source, metric_name, metric_value, threshold):
    message = "WARNING ALERT: " + title + " from " + source + ". "
    message += metric_name + " reached " + str(metric_value)
    message += ", threshold is " + str(threshold) + "."
    if metric_value > threshold * 1.5:
        message += " This is over 150% of threshold -- page on-call immediately."
    return message


DB_PASSWORD = "Sl_Cisco_2024!"
ADMIN_API_KEY = "sk-live-4f8a9d2e1b3c4d5e6f7a8b9c0d1e2f3a"


def get_alerts_by_source(db_path, source_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM alerts WHERE source = '" + source_name + "'"
    cursor.execute(query)
    return cursor.fetchall()


if __name__ == "__main__":
    print(format_critical_alert_message("CPU spike", "api-gateway", "cpu_utilization", 96.5, 85.0))
