import os, json, csv, requests, resend
from datetime import datetime
import google.generativeai as genai

# Configuration (Set these in GitHub Secrets)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
resend.api_key = os.getenv("RESEND_API_KEY")
MY_EMAIL = os.getenv("MY_EMAIL")

model = genai.GenerativeModel('gemini-2.0-flash')
CSV_FILE = "drug_approvals.csv"

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Drug Name", "Sponsor", "Type", "Date Found", "Source URL"])

def fetch_today_notices():
    today = datetime.now().strftime('%Y-%m-%d')
    url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "conditions[agency_ids][]": "170", # FDA
        "conditions[publication_date][is]": today,
        "conditions[term]": "approval OR investigational"
    }
    r = requests.get(url, params=params)
    return r.json().get('results', []) if r.status_code == 200 else []

def analyze_with_llm(notice):
    text = f"Title: {notice['title']}\nAbstract: {notice.get('abstract', '')}"
    prompt = f"Identify if this is a new IND, NDA, or BLA drug filing/approval. Extract the Drug Name and Sponsor. Return ONLY JSON: {{\"is_relevant\": bool, \"drug\": \"str\", \"sponsor\": \"str\", \"type\": \"str\"}}"
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except: return {"is_relevant": False}

def run_agent():
    init_csv()
    with open(CSV_FILE, 'r') as f:
        existing_ids = {row[0] for row in csv.reader(f)}

    notices = fetch_today_notices()
    new_findings, email_html = [], ""

    for n in notices:
        doc_id = n['document_number']
        if doc_id in existing_ids: continue # Skip if already processed

        analysis = analyze_with_llm(n)
        if analysis.get('is_relevant'):
            source_url = n.get('html_url', f"https://www.federalregister.gov/d/{doc_id}")
            row = [doc_id, analysis['drug'], analysis['sponsor'], analysis['type'], datetime.now().date(), source_url]
            new_findings.append(row)
            email_html += f"<li><b>{analysis['drug']}</b> ({analysis['type']}) by {analysis['sponsor']}<br><a href='{source_url}'>View Official Notice</a></li><br>"

    if new_findings:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f).writerows(new_findings)
        
        resend.Emails.send({
            "from": "FDA-Agent <onboarding@resend.dev>",
            "to": [MY_EMAIL],
            "subject": f"🚨 {len(new_findings)} New FDA Filings: {datetime.now().strftime('%Y-%m-%d')}",
            "html": f"<h2>Today's Drug Intelligence Report</h2><ul>{email_html}</ul>"
        })
        print(f"Agent Action: Logged {len(new_findings)} items and sent alert.")
    else:
        print("Agent Action: No new filings found today.")

if __name__ == "__main__":
    run_agent()
