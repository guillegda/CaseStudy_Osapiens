import os
import requests
import smtplib
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Any

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# API
USE_V1 = True # change to False for using V2
API_KEY_V1 = os.getenv("API_KEY_V1")
API_KEY_V2 = os.getenv("API_KEY_V2")
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")

# Email
EMAIL_TO = os.getenv("EMAIL_TO")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = SMTP_USER

# ----------------------------------------------------------------------

def fetch_data(use_v1=True) -> List[Dict[str, Any]]:
    """
    Realiza una solicitud GET al endpoint /v1/tickets (o v2) para obtener datos de tickets.
    """
    if use_v1:
        api_key = API_KEY_V1
        endpoint = "v1"
    else:
        api_key = API_KEY_V2
        endpoint = "v2"

    if not api_key:
        logging.error("La clave API para %s no está definida. Verifique su archivo .env.", endpoint)
        return []

    url = f"{BASE_URL}/{endpoint}/tickets"
    headers = {"X-API-KEY": api_key}

    logging.info("[*] Solicitando datos de: %s", url)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Handles HTTP errors (4xx or 5xx)
        
        tickets = response.json()
        logging.info("[*] Éxito: %s tickets obtenidos.", len(tickets))
        return tickets

    except requests.exceptions.HTTPError:
        logging.error("Fallo en la solicitud HTTP. Código: %s. Detalles: %s", response.status_code, response.text)
        return []
    except requests.exceptions.RequestException as e:
        logging.error("Fallo de conexión o tiempo de espera agotado: %s", e)
        return []


def calculate_kpis(tickets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcula las métricas de negocio (KPIs) a partir de la lista de tickets.
    """
    total_tickets = len(tickets)
    if total_tickets == 0:
        return {
            "Average resolution time": "N/A",
            "Tickets per agent (Avg)": "N/A",
            "Tickets per agent (Detail)": {},
            "Percentage of resolved tickets": 0.0,
            "Customer satisfaction score (CSAT)": "N/A"
        }

    resolved_tickets_count = 0
    total_resolution_time_seconds = 0
    csat_scores = []
    agents = {}
    unique_agents = set()

    for ticket in tickets:
        status = ticket.get("Status", "").lower()
        agent_name = ticket.get("Agent")

        # tickets per agent count
        if agent_name:
            agents[agent_name] = agents.get(agent_name, 0) + 1
            unique_agents.add(agent_name)

        # resolved time only for resolved tickets and CSAT if available
        if status == "resolved":
            resolved_tickets_count += 1
            
            created_dt = ticket.get("Create Date")
            resolved_dt = ticket.get("Resolved Date")
            
            # assuming dates are in ISO format strings
            if isinstance(created_dt, datetime) and isinstance(resolved_dt, datetime):
                resolution_time = resolved_dt - created_dt
                total_resolution_time_seconds += resolution_time.total_seconds()
            
            # obtain CSAT
            csat_str = ticket.get("CSAT")
            if csat_str and isinstance(csat_str, str) and csat_str.endswith('%'):
                try:
                    score = int(csat_str.strip('%'))
                    csat_scores.append(score)
                except ValueError:
                    pass

    # --- KPIs ---
    
    # Average Resolution Time
    if resolved_tickets_count > 0:
        avg_resolution_seconds = total_resolution_time_seconds / resolved_tickets_count
        avg_resolution_time = str(timedelta(seconds=round(avg_resolution_seconds)))
    else:
        avg_resolution_time = "N/A (No resolved tickets)"

    # Average Tickets per Agent
    num_unique_agents = len(unique_agents)
    tickets_per_agent = round(total_tickets / num_unique_agents, 2) if num_unique_agents > 0 else "N/A"

    # Percentage of Resolved Tickets
    pct_resolved = round((resolved_tickets_count / total_tickets * 100), 2)

    # Customer satisfaction score (CSAT)
    total_csat_records = len(csat_scores)
    avg_csat_score = round(sum(csat_scores) / total_csat_records, 2) if total_csat_records > 0 else "N/A"

    return {
        "Average resolution time": avg_resolution_time,
        "Tickets per agent (Avg)": tickets_per_agent,
        "Tickets per agent (Detail)": agents,
        "Percentage of resolved tickets": pct_resolved,
        "Customer satisfaction score (CSAT)": avg_csat_score
    }


def generate_report(kpis: dict) -> str:
    """
    Generates an HTML report based on the calculated KPIs.
    """
    report_html = f"""
    <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h2 {{ color: #1e88e5; border-bottom: 2px solid #eee; padding-bottom: 5px; }}
                .kpi-table {{ border-collapse: collapse; width: 50%; margin-top: 20px; }}
                .kpi-table th, .kpi-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                .kpi-table th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>Technical Support KPI Report</h2>
            <p>Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.</p>
            
            <h3>Key Metrics</h3>
            <ul>
                <li><b>Average Resolution Time:</b> {kpis.get('Average resolution time')}</li>
                <li><b>% of Resolved Tickets:</b> {kpis.get('Percentage of resolved tickets')}%</li>
                <li><b>CSAT (Customer Satisfaction):</b> {kpis.get('Customer satisfaction score (CSAT)')}</li>
                <li><b>Tickets per Agent (Average):</b> {kpis.get('Tickets per agent (Avg)')}</li>
            </ul>

            <h3>Agent Workload Details</h3>
            <table class="kpi-table">
                <tr><th>Agent</th><th>Tickets Assigned</th></tr>
                {''.join(f'<tr><td>{agent}</td><td>{count}</td></tr>' for agent, count in kpis.get('Tickets per agent (Detail)', {}).items())}
            </table>
        </body>
    </html>
    """
    return report_html


def send_email(report_html: str):
    """
    Connects to the SMTP server and sends the KPI report via email.
    """
    if not all([EMAIL_TO, SMTP_SERVER, SMTP_USER, SMTP_PASSWORD]):
        logging.error("Faltan variables de entorno de configuración de correo (EMAIL_TO, SMTP_SERVER, etc.). No se puede enviar el correo.")
        return

    # build email base message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Support KPI Report - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    # add HTML part
    html_part = MIMEText(report_html, "html")
    msg.attach(html_part)

    logging.info("[*] Intentando conectar a %s:%s...", SMTP_SERVER, SMTP_PORT)
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD.replace(" ", "")) # Limpiar espacios de App Password
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        
        logging.info("[SUCCESS] Reporte de KPIs enviado exitosamente a %s.",EMAIL_TO)

    except smtplib.SMTPAuthenticationError:
        logging.error("[FAILURE] Error de autenticación SMTP. Verifique SMTP_USER y la Contraseña de Aplicación.")
    except smtplib.SMTPException as e:
        logging.error("[FAILURE] Error al enviar el correo SMTP: %s", e)
    except Exception as e:
        logging.error("[FAILURE] Error desconocido durante el envío del correo: %s", e)


# ----------------------------------------------------------------------

if __name__ == "__main__":
    logging.info("~~~ Starting Report Generation Process ~~~")

    tickets = fetch_data(use_v1=USE_V1)
    
    if tickets:

        kpis = calculate_kpis(tickets)
        logging.info("[*] KPIs Calculated.")

        report = generate_report(kpis)

        send_email(report)
    else:
        logging.info("[INFO] No tickets found to generate the report. Process Terminated.")

    logging.info("~~~ Process Finished ~~~")