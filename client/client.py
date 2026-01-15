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
USE_V1 = False # change to False for using V2
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
    Get requests to /v1/tickets (or v2) endpoint to fetch ticket data.
    """
    if use_v1:
        api_key = API_KEY_V1
        endpoint = "v1"
    else:
        api_key = API_KEY_V2
        endpoint = "v2"

    if not api_key:
        logging.error("API Key for %s is not defined. Please check your .env file.", endpoint)
        return []

    url = f"{BASE_URL}/{endpoint}/tickets"
    headers = {"X-API-KEY": api_key}

    logging.info("[*] Requesting data from: %s", url)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Handles HTTP errors (4xx or 5xx)
        
        tickets = response.json()
        logging.info("[*] Success: %s tickets obtained.", len(tickets))
        logging.info("[*] Tickets sample: %s", tickets[:2])
        return tickets

    except requests.exceptions.HTTPError:
        logging.error("HTTP request failed. Code: %s. Ditails: %s", response.status_code, response.text)
        return []
    except requests.exceptions.RequestException as e:
        logging.error("Connection failed or timeout: %s", e)
        return []

def safe_date_parse(date_value: Any) -> datetime | None:
    """
    transform various date formats into a datetime object safely.
    V1 uses ISO 8601 strings, V2 uses Unix Timestamps.
    """
    if not date_value:
        return None

    # Unix Timestamp (Integer) (V2)
    if isinstance(date_value, int):
        try:
            return datetime.fromtimestamp(date_value)
        except Exception as e:
            logging.warning("Error transforming Unix Timestamp %s. Error: %s", date_value, e)
            return None

    # ISO 8601 (String) (V1)
    if isinstance(date_value, str):
        try:
            return datetime.fromisoformat(date_value)
        except ValueError:
            try:
                return datetime.fromisoformat(date_value.replace('Z', '+00:00'))
            except Exception as e:
                logging.warning("Date format STR not recognised for %s. Error:  %s", date_value, e)
                return None

    return None

def calculate_kpis(tickets: List[Dict[str, Any]]) -> Dict[str, Any]:

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

        if status == "resolved":
            resolved_tickets_count += 1
            
            created_value = ticket.get("Create Date")
            resolved_value = ticket.get("Resolved Date")

            created_dt = safe_date_parse(created_value)
            resolved_dt = safe_date_parse(resolved_value)

            if created_dt and resolved_dt:
                resolution_time = resolved_dt - created_dt
                total_resolution_time_seconds += resolution_time.total_seconds()
            
            # obtain CSAT
            csat_raw = ticket.get("CSAT")
            if csat_raw:
                csat_str = str(csat_raw).strip() 
                if csat_str.endswith('%'):
                    clean_score_str = csat_str.rstrip('%').strip() # remove % sign and extra spaces if any from string
                else:
                    clean_score_str = csat_str
                try:
                    #from string to float to int
                    score = float(clean_score_str)
                    score_int = int(score)

                    # Validate CSAT range
                    if 0 <= score_int <= 100:
                        csat_scores.append(score_int)
                    else:
                        logging.warning("CSAT out of range (%s) for ticket ID: %s", score_int, ticket.get("TicketID", "N/A"))
                        
                except ValueError:
                    # This captures cases where clean_score_str is not a number (e.g., "Bad", "Check")
                    logging.warning("Non-numeric CSAT value ('%s') ignored for ticket ID: %s", csat_raw, ticket.get("TicketID", "N/A"))

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
            <h2>Osapiens Technical Support KPI Report</h2>
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
    report_text = f"""
    [Osapiens Technical Support KPI Report]
    Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    Key Metrics:
    ---------------------------
    * Average resolution time: {kpis.get('Average resolution time')}
    * % of Resolved Tickets: {kpis.get('Percentage of resolved tickets')}%
    * CSAT (Customer Satisfaction): {kpis.get('Customer satisfaction score (CSAT)')}
    * Tickets per Agent (Average): {kpis.get('Tickets per agent (Avg)')}

    Agent Workload Details:
    -----------------------------------------
    {''.join(f'- {agent}: {count} tickets\n' for agent, count in kpis.get('Tickets per agent (Detail)', {}).items())}
    """
    # Change the return type to include both
    return {"html": report_html, "text": report_text}


def send_email(report_parts: str):
    """
    Connects to the SMTP server and sends the KPI report via email.
    """
    if not all([EMAIL_TO, SMTP_SERVER, SMTP_USER, SMTP_PASSWORD]):
        logging.error("Missing email configuration environment variables (EMAIL_TO, SMTP_SERVER, etc.). Cannot send email.")
        return

    # build email base message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Osapiens Support KPI Report - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    # Add text part first (Standard practice: least complex part first)
    text_part = MIMEText(report_parts["text"], "plain") # 'plain' text as fallback
    msg.attach(text_part)

    # Add HTML part second
    html_part = MIMEText(report_parts["html"], "html")
    msg.attach(html_part)

    logging.info("[*] Trying to reach connection to %s:%s...", SMTP_SERVER, SMTP_PORT)
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls() # elevate to secure connection
            server.login(SMTP_USER, SMTP_PASSWORD.replace(" ", "")) # just in case clean App Password spaces: formatting issues
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        
        logging.info("[SUCCESS] KPIs succesfully sent to %s.",EMAIL_TO)

    except smtplib.SMTPAuthenticationError:
        logging.error("[FAILURE] SMTP Auth Error. Verify SMTP_USER and app password.")
    except smtplib.SMTPException as e:
        logging.error("[FAILURE] Error sending SMTP maill: %s", e)
    except Exception as e:
        logging.error("[FAILURE] Unknown Error during maill sending: %s", e)


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