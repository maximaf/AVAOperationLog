import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, time, timedelta
import requests
import json
import os
import uuid
import hashlib
import base64
import extra_streamlit_components as stx

# Inicializace CookieManageru pro ukládání přihlašovacích údajů v prohlížeči
cookie_manager = stx.CookieManager()

# Nastavení stránky
st.set_page_config(
    page_title="Avaplace Operating Log",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- SKRYTÍ VÝCHOZÍHO STREAMLIT MENU A TLAČÍTKA DEPLOY ---
hide_streamlit_style = """
<style>
    /* Skrytí horní lišty kompletně i s vyhrazeným místem */
    xxxxheader {display: none !important;}
    /* Skrytí patičky "Made with Streamlit" */
    footer {display: none !important;}
    /* Odstranění obřího zbytečného prázdného místa nahoře (výchozí padding Streamlitu) */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }
    /* Odstranění stínu/okraje u popisků v Sankey grafu a nastavení černé barvy */
    .sankey .node-label-text-path,
    .sankey .node-label,
    text.node-label,
    text.node-label-text-path {
        text-shadow: none !important;
        stroke: none !important;
        stroke-width: 0px !important;
        fill: red !important;
    }
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- SPRÁVA KONFIGURACE A ŠIFROVÁNÍ ---
CONFIG_FILE = "avaplace_credentials.json"

DEFAULT_CREDS = {
    "tenant_id": "ASOLEU",
    "client_id": "ASOLEU-MMac-lEDNb6uHckiQb6qobW0eFQ",
    "client_secret": "VBLfjbIxwJvMJQJ5O69kdV6VQp2sNrGQkUmWmXExT4mPPiiQS3PjKBvys2aSixmE",
    "scope": ""
}

ENVIRONMENTS = {
    "Alpha": "alpha.avaplace.com",
    "Beta": "beta.avaplace.com",
    "Demo": "demo.avaplace.com",
    "Dev": "dev.avaplace.com",
    "Produkce": "avaplace.com"
}

def get_machine_key():
    """Vygeneruje unikátní šifrovací klíč vázaný na hardware tohoto počítače."""
    node_id = str(uuid.getnode())
    return hashlib.sha256(node_id.encode('utf-8')).digest()

def encrypt_secret(secret):
    if not secret: 
        return ""
    key = get_machine_key()
    encoded = secret.encode('utf-8')
    encrypted = bytearray(b ^ key[i % len(key)] for i, b in enumerate(encoded))
    return "🔑_encrypted_" + base64.b64encode(encrypted).decode('utf-8')

def decrypt_secret(encrypted_text):
    if not encrypted_text or not encrypted_text.startswith("🔑_encrypted_"):
        return encrypted_text
    try:
        key = get_machine_key()
        raw_cipher = encrypted_text.replace("🔑_encrypted_", "")
        decoded = base64.b64decode(raw_cipher.encode('utf-8'))
        decrypted = bytearray(b ^ key[i % len(key)] for i, b in enumerate(decoded))
        return decrypted.decode('utf-8')
    except Exception:
        return ""

def load_config():
    # 1. Pokusíme se načíst konfiguraci z cookies prohlížeče
    try:
        cookie_val = cookie_manager.get("avaplace_config")
        if cookie_val:
            data = json.loads(cookie_val)
            for env in data:
                if "client_secret" in data[env]:
                    data[env]["client_secret"] = decrypt_secret(data[env]["client_secret"])
            return data
    except Exception:
        pass

    # 2. Záložní načtení ze souboru (zpětná kompatibilita)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for env in data:
                    if "client_secret" in data[env]:
                        data[env]["client_secret"] = decrypt_secret(data[env]["client_secret"])
                return data
        except Exception:
            pass
    return {}

def save_config(config_data):
    try:
        export_data = json.loads(json.dumps(config_data))
        for env in export_data:
            if "client_secret" in export_data[env]:
                export_data[env]["client_secret"] = encrypt_secret(export_data[env]["client_secret"])
                
        # Uložíme do cookies prohlížeče na 30 dní
        cookie_manager.set(
            "avaplace_config", 
            json.dumps(export_data), 
            expires_at=datetime.now() + timedelta(days=30)
        )
    except Exception as e:
        st.sidebar.error(f"Nepodařilo se uložit konfiguraci do prohlížeče: {e}")

# Inicializace stavů v paměti aplikace
if 'fetched_logs' not in st.session_state:
    st.session_state['fetched_logs'] = []
if 'fetched_details' not in st.session_state:
    st.session_state['fetched_details'] = {}
if 'fetched_datasources' not in st.session_state:
    st.session_state['fetched_datasources'] = {}
if 'current_offset' not in st.session_state:
    st.session_state['current_offset'] = 0
if 'active_env' not in st.session_state:
    st.session_state['active_env'] = "Alpha"

if 'credentials' not in st.session_state:
    st.session_state['credentials'] = {
        'idp_url': f"https://{ENVIRONMENTS['Alpha']}/api/asol/idp",
        'api_url': f"https://{ENVIRONMENTS['Alpha']}/api/asol/ds/api/v1/OperatingLogs",
        'tenant_id': DEFAULT_CREDS['tenant_id'],
        'client_id': DEFAULT_CREDS['client_id'],
        'client_secret': DEFAULT_CREDS['client_secret'],
        'scope': DEFAULT_CREDS['scope']
    }
if 'access_token' not in st.session_state:
    st.session_state['access_token'] = None

# Vstupní fronta (SourcingData)
if 'input_queue_items' not in st.session_state:
    st.session_state['input_queue_items'] = []
if 'input_queue_offset' not in st.session_state:
    st.session_state['input_queue_offset'] = 0
if 'input_queue_filters' not in st.session_state:
    st.session_state['input_queue_filters'] = {
        'agent_id': '',
        'client_id': '',
        'status': 'Všechny'
    }

# Výstupní fronta (QueryingData)
if 'output_queue_items' not in st.session_state:
    st.session_state['output_queue_items'] = []
if 'output_queue_offset' not in st.session_state:
    st.session_state['output_queue_offset'] = 0
if 'output_queue_filters' not in st.session_state:
    st.session_state['output_queue_filters'] = {
        'model_id': 'b6530960-bb27-4980-b1bf-80ba28e78e0e',
        'source_id': '',
        'mandant_code': '',
        'use_time': False,
        'date_from': None,
        'time_from': None,
        'date_to': None,
        'time_to': None
    }

if 'usage_stats_items' not in st.session_state:
    st.session_state['usage_stats_items'] = []
if 'usage_stats_application_code' not in st.session_state:
    st.session_state['usage_stats_application_code'] = ''
if 'usage_stats_application_options' not in st.session_state:
    st.session_state['usage_stats_application_options'] = []
if 'usage_stats_tenant_app_items' not in st.session_state:
    st.session_state['usage_stats_tenant_app_items'] = []
if 'usage_stats_include_smart_check_status' not in st.session_state:
    st.session_state['usage_stats_include_smart_check_status'] = False

# Výchozí stav pro serverové filtry
if 'api_filters' not in st.session_state:
    st.session_state['api_filters'] = {
        'operationId': "",
        'severity_level': "Všechny",
        'include_system': True,
        'agent_code': "",
        'agent_id': "",
        'source_id': "",
        'op_scope': "",
        'use_time': False,
        'date_from': None,
        'time_from': None,
        'date_to': None,
        'time_to': None
    }

# Fixní klíče pro lokální filtry detailu
if 'saved_detail_statuses' not in st.session_state:
    st.session_state['saved_detail_statuses'] = ['🔴 Error', '🟡 Warning', '🟢 Info']
if 'local_detail_status_widget' not in st.session_state:
    st.session_state['local_detail_status_widget'] = st.session_state['saved_detail_statuses']

def detail_status_changed():
    st.session_state['saved_detail_statuses'] = st.session_state['local_detail_status_widget']

# --- API KOMUNIKACE ---
def fetch_token(idp_base_url, client_id, client_secret, tenant_id, scope):
    token_url = f"{idp_base_url.rstrip('/')}/connect/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    payload = {
        'grant_type': 'client_credentials',
        'client_id': client_id.strip(),
        'client_secret': client_secret.strip(),
        'tid': tenant_id.strip()
    }
    if scope and scope.strip():
        payload['scope'] = scope.strip()
        
    response = requests.post(token_url, data=payload, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json().get("access_token")

def fetch_logs_page(api_url, token, tenant_id, limit, offset, filters=None):
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    params = {
        'limit': limit,
        'offset': offset
    }
    
    if filters:
        if filters.get('operationId'): params['OperationId'] = filters['operationId'].strip()
        if filters.get('agent_code'): params['AgentCode'] = filters['agent_code'].strip()
        if filters.get('agent_id'): params['AgentId'] = filters['agent_id'].strip()
        if filters.get('source_id'): params['SourceId'] = filters['source_id'].strip()
        if filters.get('op_scope'): params['OperationScope'] = filters['op_scope'].strip()
        
        if filters.get('severity_level') and filters.get('severity_level') != "Všechny":
            params['SeverityLevel'] = filters['severity_level']
            
        params['IncludeSystemLevel'] = 'true' if filters.get('include_system', True) else 'false'
            
        if filters.get('use_time'):
            tz_local = 'Europe/Prague'
            d_from = filters.get('date_from')
            if d_from:
                t_from = filters.get('time_from') if filters.get('time_from') is not None else time(0, 0, 0)
                dt_from_local = pd.Timestamp(datetime.combine(d_from, t_from)).tz_localize(tz_local)
                params['createdFrom'] = dt_from_local.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
                
            d_to = filters.get('date_to')
            if d_to:
                t_to = filters.get('time_to') if filters.get('time_to') is not None else time(23, 59, 59)
                dt_to_local = pd.Timestamp(datetime.combine(d_to, t_to)).tz_localize(tz_local)
                params['createdTo'] = dt_to_local.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
            
    response = requests.get(api_url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def fetch_datasource_info(api_base_url, token, tenant_id, source_id):
    base_url = api_base_url.split('/OperatingLogs')[0]
    ds_url = f"{base_url}/DataSources/{source_id.strip()}"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    response = requests.get(ds_url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

def fetch_input_queue(api_url, token, tenant_id, limit, offset, filters=None):
    base_ds_url = api_url.split('/api/v1/OperatingLogs')[0]
    enqueue_url = f"{base_ds_url}/api/v2/SourcingData/EnqueueData"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    params = {
        'limit': limit,
        'offset': offset
    }
    if filters:
        if filters.get('agent_id'):
            params['agentId'] = filters['agent_id'].strip()
        if filters.get('client_id'):
            params['clientId'] = filters['client_id'].strip()
            
    response = requests.get(enqueue_url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def fetch_output_queue(api_url, token, tenant_id, limit, offset, filters=None):
    base_ds_url = api_url.split('/api/v1/OperatingLogs')[0]
    get_data_url = f"{base_ds_url}/api/v2/QueryingData/GetData"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    params = {
        'limit': limit,
        'offset': offset
    }
    if filters:
        if filters.get('model_id'):
            params['modelId'] = filters['model_id'].strip()
        if filters.get('source_id'):
            params['sourceId'] = filters['source_id'].strip()
        if filters.get('mandant_code'):
            params['mandantCode'] = filters['mandant_code'].strip()
            
        if filters.get('use_time'):
            tz_local = 'Europe/Prague'
            d_from = filters.get('date_from')
            if d_from:
                t_from = filters.get('time_from') if filters.get('time_from') is not None else time(0, 0, 0)
                dt_from_local = pd.Timestamp(datetime.combine(d_from, t_from)).tz_localize(tz_local)
                params['modifiedFrom'] = dt_from_local.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
                
            d_to = filters.get('date_to')
            if d_to:
                t_to = filters.get('time_to') if filters.get('time_to') is not None else time(23, 59, 59)
                dt_to_local = pd.Timestamp(datetime.combine(d_to, t_to)).tz_localize(tz_local)
                params['modifiedTo'] = dt_to_local.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
                
    response = requests.get(get_data_url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def fetch_usage_statistics(api_url, token, tenant_id, application_code):
    base_ds_url = api_url.split('/api/v1/OperatingLogs')[0]
    usage_url = f"{base_ds_url}/api/v1/UsageStatistics/GetTenantsUsingApplication"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    params = {}
    if application_code and application_code.strip():
        params['applicationCode'] = application_code.strip()
    response = requests.get(usage_url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def fetch_integrated_applications(api_url, token, tenant_id):
    base_ds_url = api_url.split('/api/v1/OperatingLogs')[0]
    apps_url = f"{base_ds_url}/api/v1/IntegratedApplications?limit=333"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    response = requests.get(apps_url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()

def fetch_applications_used_by_tenants(api_url, token, tenant_id, include_smart_check_status=False):
    base_ds_url = api_url.split('/api/v1/OperatingLogs')[0]
    usage_url = f"{base_ds_url}/api/v1/UsageStatistics/GetApplicationsUsedByTenants"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant': tenant_id.strip(),
        'Accept': 'application/json'
    }
    params = {
        'includeSmartCheckStatus': 'true' if include_smart_check_status else 'false'
    }
    response = requests.get(usage_url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

# --- POMOCNÉ FUNKCE PRO ZPRACOVÁNÍ DAT ---
def determine_badge(severities):
    if isinstance(severities, str):
        severities = [severities]
    combined = " ".join(list(severities))
    if 'Error' in combined: return '🔴 Error'
    elif 'Warning' in combined: return '🟡 Warning'
    elif 'Info' in combined: return '🟢 Info'
    return '⚪ Unknown'

def determine_queue_badge(status):
    if not status:
        return '⚪ Neznámý'
    status_str = str(status).strip()
    if status_str == 'Success':
        return '🟢 Success'
    elif status_str == 'Failed':
        return '🔴 Failed'
    elif status_str == 'Canceled':
        return '⚪ Canceled'
    elif status_str == 'Pending':
        return '🟡 Pending'
    return f'🔵 {status_str}'

def clean_data(raw_list):
    df = pd.DataFrame(raw_list)
    if df.empty: return df
    
    required_columns = ['id', 'operationId', 'operationType', 'activityType', 'severity', 'createdOn', 'message', 'scopeId', 'sourceId', 'agentId', 'source']
    for col in required_columns:
        if col not in df.columns: df[col] = None

    df['severity'] = df['severity'].fillna('Unknown')
    df['severity'] = df['severity'].apply(determine_badge)

    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
            df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x) if pd.notna(x) else "")
        elif df[col].dtype == 'object' and col != 'createdOn':
            df[col] = df[col].astype(str).replace('nan', '')

    df['createdOn'] = pd.to_datetime(df['createdOn'], format='ISO8601', utc=True, errors='coerce')
    return df

# --- MODÁLNÍ DIALOGY ---
@st.dialog("🔑 Přihlášení k Avaplace API")
def show_login_dialog():
    config = load_config()
    env_names = list(ENVIRONMENTS.keys())
    
    selected_env = st.selectbox("Cílové prostředí (Stage):", env_names, index=env_names.index(st.session_state['active_env']))
    
    env_creds = config.get(selected_env, {"tenant_id": "", "client_id": "", "client_secret": "", "scope": ""})
    
    st.markdown("---")
    tenant_id = st.text_input("Tenant ID (tid):", value=env_creds.get('tenant_id', ''))
    client_id = st.text_input("Client ID:", value=env_creds.get('client_id', ''))
    client_secret = st.text_input("Client Secret:", type="password", value=env_creds.get('client_secret', ''))
    scope = st.text_input("Scope (volitelné):", value=env_creds.get('scope', ''))
    
    if st.button("Uložit do prohlížeče a přihlásit se", width="stretch"):
        config[selected_env] = {
            "tenant_id": tenant_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope
        }
        save_config(config)
        
        base_domain = ENVIRONMENTS[selected_env]
        idp_url = f"https://{base_domain}/api/asol/idp"
        api_url = f"https://{base_domain}/api/asol/ds/api/v1/OperatingLogs"
        
        try:
            token = fetch_token(idp_url, client_id, client_secret, tenant_id, scope)
            st.session_state['access_token'] = token
            st.session_state['active_env'] = selected_env
            st.session_state['credentials'] = {
                'idp_url': idp_url,
                'api_url': api_url,
                'tenant_id': tenant_id,
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': scope
            }
            st.session_state['fetched_logs'] = []
            st.session_state['fetched_details'] = {}
            st.session_state['fetched_datasources'] = {}
            st.session_state['current_offset'] = 0
            st.session_state['input_queue_items'] = []
            st.session_state['input_queue_offset'] = 0
            st.session_state['output_queue_items'] = []
            st.session_state['output_queue_offset'] = 0
            
            initial_data = fetch_logs_page(
                api_url, token, tenant_id, limit=100, offset=0, filters=st.session_state['api_filters']
            )
            
            if isinstance(initial_data, dict) and 'items' in initial_data:
                st.session_state['fetched_logs'] = initial_data['items']
            elif isinstance(initial_data, list):
                st.session_state['fetched_logs'] = initial_data
                
            st.rerun()
        except Exception as e:
            st.error(f"Přihlášení nebo stažení dat selhalo: {str(e)}")

@st.dialog("📋 Detail Custom Fields")
def show_custom_fields_modal(cf_string):
    try:
        # Převedeme string na JSON objekt
        cf_data = json.loads(cf_string)
        
        # Ošetření: někdy logovací systémy serializují JSON dvakrát, pokud to stále je string, dekódujeme znovu
        if isinstance(cf_data, str):
            cf_data = json.loads(cf_data)
            
        if isinstance(cf_data, list) and len(cf_data) > 0:
            df_cf = pd.DataFrame(cf_data)
            # Vykreslíme jako tabulku, aby šlo data myší označit a zkopírovat
            st.dataframe(df_cf, width="stretch", hide_index=True)
        else:
            st.info("Tento záznam sice pole Custom Fields obsahuje, ale nejsou v něm žádná data.")
    except Exception as e:
        st.error(f"Nepodařilo se rozparsovat JSON strukturu: {e}")
        st.code(cf_string)

# --- KOMPAKTNÍ HLAVIČKA ---
header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.markdown("### 📊 Avaplace Operating Log")
with header_col2:
    env_badge = f"({st.session_state['active_env']})" if st.session_state['active_env'] else ""
    if st.button(f"🔑 Připojení {env_badge}", width="stretch"):
        show_login_dialog()

# Zastavení aplikace, POKUD NEJSME PŘIHLÁŠENI
if not st.session_state['access_token']:
    st.info("Aplikace není připojena k API. Klikněte na tlačítko připojení vpravo nahoře pro výběr prostředí a přihlášení.")
    st.stop()


# --- TABS MONITORINGU ---
tab_logs, tab_input_queue, tab_output_queue, tab_usage_stats = st.tabs([
    "📊 Provozní logy",
    "📥 Vstupní fronta (SourcingData)",
    "📤 Výstupní fronta (QueryingData)",
    "📈 Statistika použití (UsageStatistics)"
])

with tab_logs:
    is_empty_data = len(st.session_state['fetched_logs']) == 0

    # --- SERVEROVÉ FILTRY ---
    with st.expander("📡 API Filtry (Stahování dat ze serveru)", expanded=is_empty_data):

        f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
        with f_col1:
            api_op_id = st.text_input("Operation ID:", value=st.session_state['api_filters']['operationId'])
        with f_col2:
            api_sev = st.selectbox("Minimální závažnost:", ["Všechny", "Info", "Warning", "Error"],
                                   index=["Všechny", "Info", "Warning", "Error"].index(st.session_state['api_filters']['severity_level']))
        with f_col3:
            st.markdown("<br>", unsafe_allow_html=True)
            api_sys = st.checkbox("IncludeSystemLevel", value=st.session_state['api_filters']['include_system'])

        a_col1, a_col2, a_col3, a_col4 = st.columns(4)
        with a_col1: api_agent_code = st.text_input("Agent Code:", value=st.session_state['api_filters']['agent_code'])
        with a_col2: api_agent_id = st.text_input("Agent ID:", value=st.session_state['api_filters']['agent_id'])
        with a_col3: api_source_id = st.text_input("Source ID:", value=st.session_state['api_filters']['source_id'])
        with a_col4: api_op_scope = st.text_input("Operation Scope:", value=st.session_state['api_filters']['op_scope'])

        st.markdown("---")

        use_time = st.checkbox("🗓️ Omezit stahování a zobrazení na konkrétní datum/čas", value=st.session_state['api_filters']['use_time'])
        api_date_from, api_time_from, api_date_to, api_time_to = None, None, None, None
        if use_time:
            t_col1, t_col2, t_col3, t_col4 = st.columns(4)
            with t_col1: api_date_from = st.date_input("Od data:", value=st.session_state['api_filters']['date_from'], format="DD.MM.YYYY")
            with t_col2: api_time_from = st.time_input("Čas od:", value=st.session_state['api_filters']['time_from'])
            with t_col3: api_date_to = st.date_input("Do data:", value=st.session_state['api_filters']['date_to'], format="DD.MM.YYYY")
            with t_col4: api_time_to = st.time_input("Čas do:", value=st.session_state['api_filters']['time_to'])

        if st.button("🚀 Použít API filtry a nově stáhnout", width="stretch"):
            st.session_state['api_filters'] = {
                'operationId': api_op_id,
                'severity_level': api_sev,
                'include_system': api_sys,
                'agent_code': api_agent_code,
                'agent_id': api_agent_id,
                'source_id': api_source_id,
                'op_scope': api_op_scope,
                'use_time': use_time,
                'date_from': api_date_from if use_time else None,
                'time_from': api_time_from if use_time else None,
                'date_to': api_date_to if use_time else None,
                'time_to': api_time_to if use_time else None
            }
            creds = st.session_state['credentials']
            token = st.session_state['access_token']

            with st.spinner("Stahuji data podle nových filtrů..."):
                try:
                    initial_data = fetch_logs_page(
                        creds['api_url'], token, creds['tenant_id'],
                        limit=100, offset=0, filters=st.session_state['api_filters']
                    )
                    st.session_state['fetched_logs'] = []
                    st.session_state['fetched_details'] = {}
                    st.session_state['fetched_datasources'] = {}
                    st.session_state['current_offset'] = 0

                    if isinstance(initial_data, dict) and 'items' in initial_data:
                        st.session_state['fetched_logs'] = initial_data['items']
                    elif isinstance(initial_data, list):
                        st.session_state['fetched_logs'] = initial_data

                    st.rerun()
                except Exception as e:
                    st.error(f"Stažení dat selhalo: {str(e)}")

    if is_empty_data:
        st.warning("Pro zadané API filtry nevrátil server žádná data. Upravte filtry výše.")
    else:

        # --- ZPRACOVÁNÍ DATA ---
        df_raw = clean_data(st.session_state['fetched_logs'])

        if not df_raw.empty:

            # TVRDÁ LOKÁLNÍ POJISTKA DATA A ČASU
            filters = st.session_state['api_filters']
            if filters['use_time']:
                tz_local = 'Europe/Prague'
                if filters['date_from'] is not None:
                    t_f = filters['time_from'] if filters['time_from'] is not None else time(0, 0, 0)
                    dt_from_loc = pd.Timestamp(datetime.combine(filters['date_from'], t_f)).tz_localize(tz_local)
                    df_raw = df_raw[df_raw['createdOn'] >= dt_from_loc.tz_convert('UTC')]

                if filters['date_to'] is not None:
                    t_t = filters['time_to'] if filters['time_to'] is not None else time(23, 59, 59)
                    dt_to_loc = pd.Timestamp(datetime.combine(filters['date_to'], t_t)).tz_localize(tz_local)
                    df_raw = df_raw[df_raw['createdOn'] <= dt_to_loc.tz_convert('UTC')]

            if df_raw.empty:
                st.warning("Data sice byla stažena, ale žádné události nespadají do přísného lokálního časového filtru.")
            else:

                df_clean = df_raw[df_raw['operationId'].notna() & (df_raw['operationId'] != '') & (df_raw['operationId'] != 'None')].copy()
                df_system = df_raw[df_raw['operationId'].isna() | (df_raw['operationId'] == '') | (df_raw['operationId'] == 'None')].copy()

                total_cnt = len(df_raw)
                err_cnt = len(df_raw[df_raw['severity'].astype(str).str.contains('Error')])
                warn_cnt = len(df_raw[df_raw['severity'].astype(str).str.contains('Warning')])
                min_time = df_raw['createdOn'].min()
                min_time_str = min_time.tz_convert('Europe/Prague').strftime('%Y-%m-%d %H:%M:%S') if pd.notna(min_time) else "N/A"

                # --- STAVOVÝ ŘÁDEK A STRÁNKOVÁNÍ ---
                info_col, chunk_input_col, btn_col = st.columns([6, 1, 2])

                with info_col:
                    st.markdown(f"ℹ️ **Aktuální stav paměti:** Načteno **{total_cnt}** událostí (🔴 {err_cnt} chyb, 🟡 {warn_cnt} varování). Nejstarší záznam: `{min_time_str}` (CZ)")

                with chunk_input_col:
                    chunk_size = st.number_input("Počet", min_value=10, max_value=5000, value=100, step=100, label_visibility="collapsed")

                with btn_col:
                    if st.button(f"📥 Načíst dalších {chunk_size} starších záznamů", width="stretch"):
                        creds = st.session_state['credentials']
                        token = st.session_state['access_token']

                        if not token:
                            st.error("Chybí token. Přihlaste se prosím znovu.")
                        else:
                            with st.spinner("Stahuji další data z Avaplace..."):
                                try:
                                    new_offset = st.session_state['current_offset'] + chunk_size
                                    next_data = fetch_logs_page(
                                        creds['api_url'], token, creds['tenant_id'],
                                        limit=chunk_size, offset=new_offset, filters=st.session_state['api_filters']
                                    )

                                    new_items = []
                                    if isinstance(next_data, dict) and 'items' in next_data:
                                        new_items = next_data['items']
                                    elif isinstance(next_data, list):
                                        new_items = next_data

                                    if new_items:
                                        combined_logs = st.session_state['fetched_logs'] + new_items
                                        unique_logs = {item['id']: item for item in combined_logs if 'id' in item}.values()
                                        st.session_state['fetched_logs'] = list(unique_logs)
                                        st.session_state['current_offset'] = new_offset
                                        st.rerun()
                                    else:
                                        st.info("Konec historie. Žádné další záznamy server nevrátil.")
                                except Exception as e:
                                    st.error(f"Nepodařilo se stáhnout další data: {str(e)}")

                # --- HLAVNÍ SEZNACOVACÍ GRID ---
                st.subheader("🗂️ Seznam operačních cyklů")

                # Agregace dat pro Master tabulku
                df_master_base = df_clean.groupby('operationId').agg(
                    První_výskyt=('createdOn', 'min'),
                    Počet_událostí=('id', 'count'),
                    Vsechny_zavaznosti=('severity', lambda x: set(x))
                ).reset_index()

                df_master_base['Stav'] = df_master_base['Vsechny_zavaznosti'].apply(determine_badge)
                df_master_base = df_master_base[['Stav', 'operationId', 'První_výskyt', 'Počet_událostí']]

                df_master_filtered = df_master_base.sort_values(by='První_výskyt', ascending=False).reset_index(drop=True)

                selection_event = st.dataframe(
                    df_master_filtered,
                    width="stretch",
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun"
                )

                active_op_id = None
                if selection_event.selection.rows:
                    selected_idx = selection_event.selection.rows[0]
                    if selected_idx < len(df_master_filtered):
                        active_op_id = df_master_filtered.iloc[selected_idx]['operationId']
                elif not df_master_filtered.empty:
                    active_op_id = df_master_filtered.iloc[0]['operationId']

                # --- LAZY LOADING DETAILU ---
                if active_op_id:
                    if active_op_id not in st.session_state['fetched_details']:
                        creds = st.session_state['credentials']
                        token = st.session_state['access_token']
                        full_context_filters = {'operationId': active_op_id}

                        with st.spinner("Dotahuji kompletní kontext událostí pro tuto operaci..."):
                            try:
                                detail_data = fetch_logs_page(creds['api_url'], token, creds['tenant_id'], limit=1000, offset=0, filters=full_context_filters)

                                new_items = []
                                if isinstance(detail_data, dict) and 'items' in detail_data:
                                    new_items = detail_data['items']
                                elif isinstance(detail_data, list):
                                    new_items = detail_data

                                st.session_state['fetched_details'][active_op_id] = new_items
                            except Exception as e:
                                st.error(f"Nepodařilo se stáhnout detail operace: {str(e)}")

                # --- DETAILNÍ GRID A JEHO FILTR ---
                if active_op_id:
                    st.markdown("---")
                    det_header_col, det_filter_col = st.columns([2, 1])

                    with det_header_col:
                        st.subheader(f"📄 Detailní výpis událostí pro OperationID: `{active_op_id}`")
                        st.markdown("Kliknutím na řádek zobrazíte pod tabulkou **Custom Fields** nebo metadata k **SourceID**.")

                    with det_filter_col:
                        all_available_statuses = ['🔴 Error', '🟡 Warning', '🟢 Info']
                        selected_detail_statuses = st.multiselect(
                            "Filtrovat zobrazené události v detailu:",
                            options=all_available_statuses,
                            key="local_detail_status_widget",
                            on_change=detail_status_changed
                        )

                    local_detail_logs = [item for item in st.session_state['fetched_logs'] if item.get('operationId') == active_op_id]
                    downloaded_detail_logs = st.session_state['fetched_details'].get(active_op_id, [])

                    combined_detail_logs = local_detail_logs + downloaded_detail_logs
                    unique_detail_logs = {item['id']: item for item in combined_detail_logs if 'id' in item}.values()

                    df_detail_raw = clean_data(list(unique_detail_logs))

                    if df_detail_raw.empty:
                        st.info("Pro vybranou operaci nebyly nalezeny žádné detailní události.")
                    else:
                        df_detail = df_detail_raw.copy()

                        if len(selected_detail_statuses) > 0:
                            df_detail = df_detail[df_detail['severity'].isin(selected_detail_statuses)]

                        df_detail = df_detail.sort_values(by='createdOn').reset_index(drop=True)

                        display_columns = ['severity', 'operationType', 'activityType', 'createdOn', 'message', 'source', 'scopeId', 'agentId', 'sourceId', 'customFields', 'details']
                        existing_cols = [c for c in display_columns if c in df_detail.columns]
                        other_cols = [c for c in df_detail.columns if c not in display_columns and c != 'Stav']

                        df_display = df_detail[existing_cols + other_cols]

                        detail_selection = st.dataframe(
                            df_display,
                            width="content",
                            hide_index=True,
                            selection_mode="single-row",
                            on_select="rerun",
                            column_config={
                                "customFields": st.column_config.TextColumn("customFields", width="large"),
                                "details": st.column_config.TextColumn("details", width="large")
                            }
                        )

                        # --- ROZŠÍŘENÁ METADATA (LOOKUPS & CUSTOM FIELDS) ---
                        active_detail_row = None
                        if detail_selection.selection.rows:
                            selected_det_idx = detail_selection.selection.rows[0]
                            if selected_det_idx < len(df_display):
                                active_detail_row = df_display.iloc[selected_det_idx]

                        if active_detail_row is not None:
                            st.markdown("#### 🔗 Rozšířené detaily vybraného řádku")

                            # 1. Řešení pro Custom Fields (Spustí modální okno)
                            custom_fields_raw = active_detail_row.get('customFields')
                            if pd.notna(custom_fields_raw) and str(custom_fields_raw).strip() not in ['', '[]', 'None', 'null']:
                                if st.button("📋 Otevřít 'Custom Fields' v přehledné tabulce", width="stretch"):
                                    show_custom_fields_modal(str(custom_fields_raw))

                            # 2. Řešení pro Source ID metadata (Automaticky dotáhne a vykreslí expander)
                            source_id = active_detail_row.get('sourceId')
                            if pd.notna(source_id) and str(source_id).strip().lower() not in ['', 'none', 'nan', 'null']:
                                source_id_str = str(source_id).strip()
                                creds = st.session_state['credentials']
                                token = st.session_state['access_token']

                                if source_id_str not in st.session_state['fetched_datasources']:
                                    with st.spinner(f"Dotahuji metadata pro DataSource: {source_id_str}..."):
                                        try:
                                            ds_info = fetch_datasource_info(creds['api_url'], token, creds['tenant_id'], source_id_str)
                                            st.session_state['fetched_datasources'][source_id_str] = ds_info
                                        except Exception as e:
                                            st.error(f"Nepodařilo se stáhnout metadata pro DataSource '{source_id_str}': {e}")

                                ds_data = st.session_state['fetched_datasources'].get(source_id_str)
                                if ds_data:
                                    with st.expander(f"📦 API Data Source Info: {ds_data.get('name', source_id_str)}", expanded=True):
                                        st.json(ds_data)

                        with st.expander("⏱️ Časová osa událostí operace", expanded=False):
                            for idx, row in df_detail.iterrows():
                                t_val = row['createdOn']
                                t_str = t_val.tz_convert('Europe/Prague').strftime('%H:%M:%S.%f')[:-3] if pd.notna(t_val) else "Neznámý čas"
                                st.markdown(f"**{t_str}** | {row['severity']} `[{row.get('operationType', 'Unknown')}]` — **{row.get('activityType', 'Unknown')}** (*{row.get('source', 'Neznámý zdroj')}*)")
                                st.caption(f"↳ {row.get('message', '')}")
                else:
                    st.info("Vyberte operaci v horní tabulce pro zobrazení detailu.")

                # --- VOLITELNÉ POHLEDY (SCHOVANÉ) ---
                with st.expander("📊 Globální analytické pohledy (Sankey & Výpočty trvání)", expanded=False):
                    col_g1, col_g2 = st.columns(2)

                    with col_g1:
                        st.markdown("##### Doba zpracování Performance úseků (ScopeID)")
                        if active_op_id and 'df_detail' in locals() and not df_detail.empty:

                            mask_begin = df_detail['activityType'].astype(str).str.endswith('|Begin')
                            mask_end = df_detail['activityType'].astype(str).str.endswith('|End')

                            begins = df_detail[mask_begin].set_index('scopeId')
                            ends = df_detail[mask_end].set_index('scopeId')

                            durations = []
                            for s_id in begins.index.intersection(ends.index):
                                if pd.notna(s_id) and str(s_id) != 'None' and str(s_id) != '':
                                    b_time = begins.loc[s_id, 'createdOn']
                                    e_time = ends.loc[s_id, 'createdOn']

                                    if isinstance(b_time, pd.Series): b_time = b_time.iloc[0]
                                    if isinstance(e_time, pd.Series): e_time = e_time.iloc[0]

                                    if pd.notna(b_time) and pd.notna(e_time):
                                        durations.append({"ScopeId": s_id, "Trvání (s)": (e_time - b_time).total_seconds()})

                            if durations:
                                df_dur = pd.DataFrame(durations)
                                fig_dur = px.bar(df_dur, x='ScopeId', y='Trvání (s)', text='Trvání (s)', title="Časové úseky")
                                fig_dur.update_traces(texttemplate='%{text:.3f} s', textposition='outside')
                                st.plotly_chart(fig_dur, width="stretch")
                            else:
                                st.info("Vybraná operace neobsahuje spárované dvojice končící na |Begin a |End se shodným ScopeId.")
                        else:
                            st.info("Žádaná data pro výpočet.")

                    with col_g2:
                        st.markdown("##### Tok fází a závažností (Sankey)")
                        if not df_clean.empty and 'operationType' in df_clean.columns and 'severity' in df_clean.columns:
                            sankey_data = df_clean.groupby(['operationType', 'severity']).size().reset_index(name='count')
                            all_nodes = list(df_clean['operationType'].unique()) + list(df_clean['severity'].unique())
                            node_indices = {node: idx for idx, node in enumerate(all_nodes)}

                            sources = [node_indices[row['operationType']] for _, row in sankey_data.iterrows()]
                            targets = [node_indices[row['severity']] for _, row in sankey_data.iterrows()]
                            values = sankey_data['count'].tolist()

                            # Výpočet průměrné doby trvání jednotlivých fází v sekundách (počítáno za každou operaci zvlášť)
                            phase_durations = {}
                            for phase in df_clean['operationType'].unique():
                                phase_df = df_clean[df_clean['operationType'] == phase]
                                if not phase_df.empty:
                                    op_groups = phase_df.groupby('operationId')
                                    durations = []
                                    for _, op_df in op_groups:
                                        p_min = op_df['createdOn'].min()
                                        p_max = op_df['createdOn'].max()
                                        if pd.notna(p_min) and pd.notna(p_max):
                                            durations.append((p_max - p_min).total_seconds())
                                    if durations:
                                        avg_dur = sum(durations) / len(durations)
                                        phase_durations[phase] = f"ø {avg_dur:.3f} s"
                                    else:
                                        phase_durations[phase] = "0.000 s"
                                else:
                                    phase_durations[phase] = "N/A"

                            # Příprava popisků pro uzly (nodes)
                            all_nodes_labels = []
                            for node in all_nodes:
                                node_str = str(node)
                                if node_str in phase_durations:
                                    all_nodes_labels.append(f"{node_str} ({phase_durations[node_str]})")
                                else:
                                    all_nodes_labels.append(node_str)

                            # Definování harmonických barev pro uzly
                            node_colors = []
                            for node in all_nodes:
                                node_str = str(node)
                                if 'Error' in node_str:
                                    node_colors.append('#ef5350') # jemná červená
                                elif 'Warning' in node_str:
                                    node_colors.append('#ffca28') # jemná žlutá
                                elif 'Info' in node_str:
                                    node_colors.append('#66bb6a') # jemná zelená
                                elif node_str == 'InputData':
                                    node_colors.append('#29b6f6') # modrá
                                elif node_str == 'Transform':
                                    node_colors.append('#ab47bc') # fialová
                                elif node_str == 'ConsumeData':
                                    node_colors.append('#ffa726') # oranžová
                                else:
                                    node_colors.append('#26a69a') # fallback teal

                            if sources and targets:
                                fig_sankey = go.Figure(data=[go.Sankey(
                                    node=dict(
                                        pad=25, 
                                        thickness=20, 
                                        line=dict(color="black", width=0.5), 
                                        label=all_nodes_labels, 
                                        color=node_colors
                                    ),
                                    link=dict(
                                        source=sources, 
                                        target=targets, 
                                        value=values, 
                                        color="rgba(100, 149, 237, 0.15)"
                                    )
                                )])
                                fig_sankey.update_layout(
                                    font=dict(family="Outfit, Inter, sans-serif", size=12, color="black"),
                                    height=350,
                                    margin=dict(l=10, r=10, t=10, b=10)
                                )
                                st.plotly_chart(fig_sankey, width="stretch")

                if 'df_system' in locals() and not df_system.empty:
                    with st.expander("⚙️ Systémové/Infrastrukturní události platformy (bez OperationID)", expanded=False):
                        st.dataframe(df_system, width="stretch", hide_index=True)


with tab_input_queue:
    st.markdown("### 📥 Vstupní fronta (SourcingData)")
    st.markdown("Sledování příchozích datových balíčků odesílaných integračními agenty.")
    
    # Filtry
    with st.expander("📡 Filtry vstupní fronty", expanded=True):
        iq_col1, iq_col2 = st.columns(2)
        with iq_col1:
            iq_agent_id = st.text_input("Agent ID (Enqueue):", value=st.session_state['input_queue_filters']['agent_id'])
        with iq_col2:
            iq_client_id = st.text_input("Client ID (Enqueue):", value=st.session_state['input_queue_filters']['client_id'])
            
        iq_status = st.selectbox("Filtrovat stav (lokálně):", ["Všechny", "Success", "Failed", "Pending", "Canceled"],
                                 index=["Všechny", "Success", "Failed", "Pending", "Canceled"].index(st.session_state['input_queue_filters']['status']))
        
        if st.button("🚀 Načíst / Aktualizovat vstupní frontu", key="btn_load_input_queue"):
            st.session_state['input_queue_filters'] = {
                'agent_id': iq_agent_id,
                'client_id': iq_client_id,
                'status': iq_status
            }
            st.session_state['input_queue_offset'] = 0
            st.session_state['input_queue_items'] = []
            
            with st.spinner("Načítám vstupní frontu..."):
                try:
                    data = fetch_input_queue(
                        st.session_state['credentials']['api_url'],
                        st.session_state['access_token'],
                        st.session_state['credentials']['tenant_id'],
                        limit=100,
                        offset=0,
                        filters=st.session_state['input_queue_filters']
                    )
                    if isinstance(data, dict) and 'items' in data:
                        st.session_state['input_queue_items'] = data['items']
                    elif isinstance(data, list):
                        st.session_state['input_queue_items'] = data
                    st.rerun()
                except Exception as e:
                    st.error(f"Načtení vstupní fronty selhalo: {e}")
                    
    # Auto-fetch if empty
    if not st.session_state['input_queue_items'] and st.session_state['access_token']:
        try:
            with st.spinner("Automatické načítání vstupní fronty..."):
                data = fetch_input_queue(
                    st.session_state['credentials']['api_url'],
                    st.session_state['access_token'],
                    st.session_state['credentials']['tenant_id'],
                    limit=100,
                    offset=0,
                    filters=st.session_state['input_queue_filters']
                )
                if isinstance(data, dict) and 'items' in data:
                    st.session_state['input_queue_items'] = data['items']
                elif isinstance(data, list):
                    st.session_state['input_queue_items'] = data
        except Exception as e:
            st.info(f"Pro načtení dat klikněte na tlačítko výše. (Detail chyby: {e})")

    # Vykreslení tabulky
    if st.session_state['input_queue_items']:
        df_iq = pd.DataFrame(st.session_state['input_queue_items'])
        
        # Ošetření sloupců
        required_cols = ['queueItemId', 'operationId', 'createdOn', 'completedOn', 'finishedOn', 'status', 'wasSuccess', 'wasFailure', 'errorMessage']
        for col in required_cols:
            if col not in df_iq.columns:
                df_iq[col] = None
                
        df_iq['Stav'] = df_iq['status'].apply(determine_queue_badge)
        
        # Lokální filtrování stavu
        status_filter = st.session_state['input_queue_filters']['status']
        if status_filter != "Všechny":
            df_iq = df_iq[df_iq['status'] == status_filter]
            
        # Převod dat a výpočet trvání
        df_iq['createdOn'] = pd.to_datetime(df_iq['createdOn'], utc=True, errors='coerce')
        df_iq['completedOn'] = pd.to_datetime(df_iq['completedOn'], utc=True, errors='coerce')
        df_iq['finishedOn'] = pd.to_datetime(df_iq['finishedOn'], utc=True, errors='coerce')
        
        # Doba zpracování: finishedOn - createdOn
        df_iq['Doba zpracování (s)'] = (df_iq['finishedOn'] - df_iq['createdOn']).dt.total_seconds().round(2)
        
        # Vytvoření zobrazení
        df_iq_display = df_iq.copy()
        
        # Zformátování sloupců pro tabulku
        tz_local = 'Europe/Prague'
        for col in ['createdOn', 'completedOn', 'finishedOn']:
            df_iq_display[col] = df_iq_display[col].dt.tz_convert(tz_local).dt.strftime('%d.%m.%Y %H:%M:%S')
            df_iq_display[col] = df_iq_display[col].fillna('N/A')
            
        df_iq_display = df_iq_display.sort_values(by='createdOn', ascending=False).reset_index(drop=True)
        
        st.markdown("#### 🗂️ Seznam položek ve vstupní frontě")
        
        # Paging visual chunk loader
        info_col_iq, chunk_col_iq, btn_col_iq = st.columns([6, 1, 2])
        with info_col_iq:
            st.markdown(f"ℹ️ Zobrazeno **{len(df_iq_display)}** položek ve frontě.")
        with chunk_col_iq:
            chunk_size_iq = st.number_input("Počet iq", min_value=10, max_value=5000, value=100, step=100, label_visibility="collapsed", key="chunk_size_iq")
        with btn_col_iq:
            if st.button(f"📥 Načíst dalších {chunk_size_iq} starších", key="btn_load_more_iq", width="stretch"):
                try:
                    new_offset = st.session_state['input_queue_offset'] + chunk_size_iq
                    data_more = fetch_input_queue(
                        st.session_state['credentials']['api_url'],
                        st.session_state['access_token'],
                        st.session_state['credentials']['tenant_id'],
                        limit=chunk_size_iq,
                        offset=new_offset,
                        filters=st.session_state['input_queue_filters']
                    )
                    new_items = data_more.get('items', []) if isinstance(data_more, dict) else data_more
                    if new_items:
                        combined = st.session_state['input_queue_items'] + new_items
                        unique = {item['queueItemId']: item for item in combined if 'queueItemId' in item}.values()
                        st.session_state['input_queue_items'] = list(unique)
                        st.session_state['input_queue_offset'] = new_offset
                        st.rerun()
                    else:
                        st.info("Žádné další záznamy ve vstupní frontě.")
                except Exception as e:
                    st.error(f"Nepodařilo se načíst další data: {e}")
                    
        selection_iq = st.dataframe(
            df_iq_display[['Stav', 'queueItemId', 'operationId', 'createdOn', 'finishedOn', 'Doba zpracování (s)', 'errorMessage']],
            width="stretch",
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="df_iq_table"
        )
        
        selected_iq_row = None
        if selection_iq.selection.rows:
            sel_idx = selection_iq.selection.rows[0]
            if sel_idx < len(df_iq_display):
                selected_iq_row = df_iq_display.iloc[sel_idx]
                
        if selected_iq_row is not None:
            st.markdown("#### 🔍 Detail vybrané položky")
            
            # Zobrazení chybové zprávy
            err_msg = selected_iq_row.get('errorMessage')
            if pd.notna(err_msg) and str(err_msg).strip():
                st.error(f"**Chybová zpráva:** {err_msg}")
                
            st.json(selected_iq_row.to_dict())
            
            op_id_iq = selected_iq_row.get('operationId')
            if pd.notna(op_id_iq) and str(op_id_iq).strip() not in ['', 'None']:
                if st.button("🔍 Zobrazit tuto operaci v Provozním logu", key="btn_link_iq_to_log"):
                    st.session_state['api_filters']['operationId'] = str(op_id_iq)
                    st.session_state['api_filters']['severity_level'] = "Všechny"
                    st.session_state['fetched_logs'] = []
                    st.session_state['fetched_details'] = {}
                    st.session_state['current_offset'] = 0
                    
                    try:
                        initial_data = fetch_logs_page(
                            st.session_state['credentials']['api_url'],
                            st.session_state['access_token'],
                            st.session_state['credentials']['tenant_id'],
                            limit=100,
                            offset=0,
                            filters=st.session_state['api_filters']
                        )
                        if isinstance(initial_data, dict) and 'items' in initial_data:
                            st.session_state['fetched_logs'] = initial_data['items']
                        elif isinstance(initial_data, list):
                            st.session_state['fetched_logs'] = initial_data
                    except Exception:
                        pass
                        
                    st.toast("Operace byla předfiltrována. Přepněte se na záložku 'Provozní logy'.", icon="📊")
                    st.rerun()
    else:
        st.info("Vstupní fronta je prázdná nebo nebyla načtena.")



with tab_output_queue:
    st.markdown("### 📤 Výstupní fronta (QueryingData)")
    st.markdown("Sledování datových záznamů publikovaných a připravených ke stažení.")
    
    # Filtry
    with st.expander("📡 Filtry výstupní fronty", expanded=True):
        oq_col1, oq_col2 = st.columns(2)
        with oq_col1:
            oq_model_id = st.text_input("Data Model ID (povinné):", value=st.session_state['output_queue_filters']['model_id'])
        with oq_col2:
            oq_source_id = st.text_input("Source ID (volitelné):", value=st.session_state['output_queue_filters']['source_id'])
            
        oq_col3, oq_col4 = st.columns(2)
        with oq_col3:
            oq_mandant = st.text_input("Mandant Code (volitelné):", value=st.session_state['output_queue_filters']['mandant_code'])
        with oq_col4:
            st.markdown("<br>", unsafe_allow_html=True)
            oq_use_time = st.checkbox("Omezit datum modifikace", value=st.session_state['output_queue_filters']['use_time'], key="oq_use_time")
            
        oq_date_from, oq_time_from, oq_date_to, oq_time_to = None, None, None, None
        if oq_use_time:
            oq_t_col1, oq_t_col2, oq_t_col3, oq_t_col4 = st.columns(4)
            with oq_t_col1:
                oq_date_from = st.date_input("Od data (modifikováno):", value=st.session_state['output_queue_filters'].get('date_from'), format="DD.MM.YYYY", key="oq_date_from")
            with oq_t_col2:
                oq_time_from = st.time_input("Čas od (modifikováno):", value=st.session_state['output_queue_filters'].get('time_from'), key="oq_time_from")
            with oq_t_col3:
                oq_date_to = st.date_input("Do data (modifikováno):", value=st.session_state['output_queue_filters'].get('date_to'), format="DD.MM.YYYY", key="oq_date_to")
            with oq_t_col4:
                oq_time_to = st.time_input("Čas do (modifikováno):", value=st.session_state['output_queue_filters'].get('time_to'), key="oq_time_to")
                
        if st.button("🚀 Načíst / Aktualizovat výstupní frontu", key="btn_load_output_queue"):
            if not oq_model_id.strip():
                st.error("Pro načtení výstupní fronty je nutné vyplnit 'Data Model ID'!")
            else:
                st.session_state['output_queue_filters'] = {
                    'model_id': oq_model_id,
                    'source_id': oq_source_id,
                    'mandant_code': oq_mandant,
                    'use_time': oq_use_time,
                    'date_from': oq_date_from,
                    'time_from': oq_time_from,
                    'date_to': oq_date_to,
                    'time_to': oq_time_to
                }
                st.session_state['output_queue_offset'] = 0
                st.session_state['output_queue_items'] = []
                
                with st.spinner("Načítám výstupní frontu..."):
                    try:
                        data = fetch_output_queue(
                            st.session_state['credentials']['api_url'],
                            st.session_state['access_token'],
                            st.session_state['credentials']['tenant_id'],
                            limit=100,
                            offset=0,
                            filters=st.session_state['output_queue_filters']
                        )
                        if isinstance(data, dict) and 'items' in data:
                            st.session_state['output_queue_items'] = data['items']
                        elif isinstance(data, list):
                            st.session_state['output_queue_items'] = data
                        st.rerun()
                    except Exception as e:
                        st.error(f"Načtení výstupní fronty selhalo: {e}")
                        
    # Auto-fetch if empty and model_id exists
    if not st.session_state['output_queue_items'] and st.session_state['output_queue_filters']['model_id'] and st.session_state['access_token']:
        try:
            with st.spinner("Automatické načítání výstupní fronty..."):
                data = fetch_output_queue(
                    st.session_state['credentials']['api_url'],
                    st.session_state['access_token'],
                    st.session_state['credentials']['tenant_id'],
                    limit=100,
                    offset=0,
                    filters=st.session_state['output_queue_filters']
                )
                if isinstance(data, dict) and 'items' in data:
                    st.session_state['output_queue_items'] = data['items']
                elif isinstance(data, list):
                    st.session_state['output_queue_items'] = data
        except Exception as e:
            st.info(f"Pro načtení dat klikněte na tlačítko výše. (Detail chyby: {e})")

    # Vykreslení tabulky
    if st.session_state['output_queue_items']:
        df_oq = pd.DataFrame(st.session_state['output_queue_items'])
        
        if 'Id' in df_oq.columns:
            def extract_record_id(x):
                if isinstance(x, dict):
                    return x.get('RecordId', '')
                elif isinstance(x, str):
                    try:
                        val = json.loads(x)
                        return val.get('RecordId', '')
                    except:
                        pass
                return str(x)
            df_oq['RecordId'] = df_oq['Id'].apply(extract_record_id)
        else:
            df_oq['RecordId'] = None
            
        for col in ['ExternalId', 'SourceId', 'MandantCode', 'UtcModifiedOn', 'deleted']:
            if col not in df_oq.columns:
                df_oq[col] = None
                
        df_oq['Stav'] = df_oq['deleted'].apply(lambda x: '🔴 Deleted' if x is True or str(x).lower() == 'true' else '🟢 Active')
        
        df_oq['UtcModifiedOn'] = pd.to_datetime(df_oq['UtcModifiedOn'], utc=True, errors='coerce')
        df_oq_display = df_oq.copy()
        
        tz_local = 'Europe/Prague'
        df_oq_display['UtcModifiedOn'] = df_oq_display['UtcModifiedOn'].dt.tz_convert(tz_local).dt.strftime('%d.%m.%Y %H:%M:%S')
        df_oq_display['UtcModifiedOn'] = df_oq_display['UtcModifiedOn'].fillna('N/A')
        
        st.markdown("#### 🗂️ Seznam záznamů ve výstupní frontě")
        
        # Paging visual chunk loader
        info_col_oq, chunk_col_oq, btn_col_oq = st.columns([6, 1, 2])
        with info_col_oq:
            st.markdown(f"ℹ️ Zobrazeno **{len(df_oq_display)}** publikovaných záznamů.")
        with chunk_col_oq:
            chunk_size_oq = st.number_input("Počet oq", min_value=10, max_value=5000, value=100, step=100, label_visibility="collapsed", key="chunk_size_oq")
        with btn_col_oq:
            if st.button(f"📥 Načíst dalších {chunk_size_oq} starších", key="btn_load_more_oq", width="stretch"):
                try:
                    new_offset = st.session_state['output_queue_offset'] + chunk_size_oq
                    data_more = fetch_output_queue(
                        st.session_state['credentials']['api_url'],
                        st.session_state['access_token'],
                        st.session_state['credentials']['tenant_id'],
                        limit=chunk_size_oq,
                        offset=new_offset,
                        filters=st.session_state['output_queue_filters']
                    )
                    new_items = data_more.get('items', []) if isinstance(data_more, dict) else data_more
                    if new_items:
                        combined = st.session_state['output_queue_items'] + new_items
                        def get_item_key(item):
                            if 'ExternalId' in item and item['ExternalId']:
                                return item['ExternalId']
                            if 'Id' in item and isinstance(item['Id'], dict):
                                return item['Id'].get('RecordId', '')
                            return str(item)
                        
                        unique = {}
                        for item in combined:
                            k = get_item_key(item)
                            unique[k] = item
                            
                        st.session_state['output_queue_items'] = list(unique.values())
                        st.session_state['output_queue_offset'] = new_offset
                        st.rerun()
                    else:
                        st.info("Žádné další publikované záznamy.")
                except Exception as e:
                    st.error(f"Nepodařilo se načíst další data: {e}")
                    
        pref_cols = ['Stav', 'UtcModifiedOn', 'RecordId', 'ExternalId', 'MandantCode', 'SourceId']
        display_cols_oq = [c for c in pref_cols if c in df_oq_display.columns]
        
        for ext_c in ['Code', 'Name']:
            if ext_c in df_oq_display.columns:
                display_cols_oq.append(ext_c)
                
        selection_oq = st.dataframe(
            df_oq_display[display_cols_oq],
            width="stretch",
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="df_oq_table"
        )
        
        selected_oq_row = None
        if selection_oq.selection.rows:
            sel_idx = selection_oq.selection.rows[0]
            if sel_idx < len(df_oq_display):
                selected_oq_row = df_oq_display.iloc[sel_idx]
                
        if selected_oq_row is not None:
            st.markdown("#### 🔍 Detail vybraného záznamu")
            st.json(selected_oq_row.to_dict())
            
            op_id_oq = selected_oq_row.get('operationId')
            if op_id_oq is None:
                for val in selected_oq_row:
                    if isinstance(val, dict) and 'operationId' in val:
                        op_id_oq = val['operationId']
                        break
                        
            if pd.notna(op_id_oq) and str(op_id_oq).strip() not in ['', 'None']:
                if st.button("🔍 Zobrazit tuto operaci v Provozním logu", key="btn_link_oq_to_log"):
                    st.session_state['api_filters']['operationId'] = str(op_id_oq)
                    st.session_state['api_filters']['severity_level'] = "Všechny"
                    st.session_state['fetched_logs'] = []
                    st.session_state['fetched_details'] = {}
                    st.session_state['current_offset'] = 0
                    
                    try:
                        initial_data = fetch_logs_page(
                            st.session_state['credentials']['api_url'],
                            st.session_state['access_token'],
                            st.session_state['credentials']['tenant_id'],
                            limit=100,
                            offset=0,
                            filters=st.session_state['api_filters']
                        )
                        if isinstance(initial_data, dict) and 'items' in initial_data:
                            st.session_state['fetched_logs'] = initial_data['items']
                        elif isinstance(initial_data, list):
                            st.session_state['fetched_logs'] = initial_data
                    except Exception:
                        pass
                        
                    st.toast("Operace byla předfiltrována. Přepněte se na záložku 'Provozní logy'.", icon="📊")
                    st.rerun()
    else:
        st.info("Výstupní fronta je prázdná nebo nebyla načtena.")


with tab_usage_stats:
    st.markdown("### 📈 Statistika použití (UsageStatistics)")
    st.info("Poznámka: statistika použití je dostupná pouze pro ASOLEU připojení.")

    with st.expander("🔹 Statistika použití podle aplikace", expanded=True):
        if 'usage_stats_application_options' not in st.session_state:
            st.session_state['usage_stats_application_options'] = []

        application_options = st.session_state['usage_stats_application_options']
        if not application_options:
            try:
                with st.spinner("Načítám seznam aplikací ..."):
                    integrated_apps_data = fetch_integrated_applications(
                        st.session_state['credentials']['api_url'],
                        st.session_state['access_token'],
                        st.session_state['credentials']['tenant_id']
                    )
                if isinstance(integrated_apps_data, dict) and 'items' in integrated_apps_data:
                    app_items = integrated_apps_data['items']
                elif isinstance(integrated_apps_data, list):
                    app_items = integrated_apps_data
                else:
                    app_items = []
                application_options = [item.get('code') for item in app_items if isinstance(item, dict) and item.get('code')]
                st.session_state['usage_stats_application_options'] = application_options
            except Exception as e:
                st.error(f"Nelze načíst seznam aplikací: {e}")
                application_options = []

        application_code_options = ["-- Vyberte aplikaci --"] + application_options
        selected_index = 0
        if st.session_state['usage_stats_application_code'] in application_options:
            selected_index = application_options.index(st.session_state['usage_stats_application_code']) + 1
        application_code = st.selectbox("Application Code:", options=application_code_options, index=selected_index)
        if application_code == "-- Vyberte aplikaci --":
            application_code = ""

        if st.button("🚀 Načíst statistiku použití", key="btn_load_usage_stats"):
            if not application_code.strip():
                st.error("Zadejte prosím 'Application Code' pro načtení statistik použití.")
            else:
                st.session_state['usage_stats_application_code'] = application_code.strip()
                st.session_state['usage_stats_items'] = []
                with st.spinner("Načítám UsageStatistics ..."):
                    try:
                        usage_data = fetch_usage_statistics(
                            st.session_state['credentials']['api_url'],
                            st.session_state['access_token'],
                            st.session_state['credentials']['tenant_id'],
                            application_code
                        )
                        if isinstance(usage_data, dict) and 'items' in usage_data:
                            st.session_state['usage_stats_items'] = usage_data['items']
                        elif isinstance(usage_data, list):
                            st.session_state['usage_stats_items'] = usage_data
                        else:
                            st.session_state['usage_stats_items'] = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Načtení UsageStatistics selhalo: {e}")

        if st.session_state['usage_stats_items']:
            df_usage = pd.DataFrame(st.session_state['usage_stats_items'])
            desired_columns = ['tenantName', 'tenantId', 'ownerOrgName', 'ownerOrgCode', 'ownerOrgId']
            df_usage = df_usage[[c for c in desired_columns if c in df_usage.columns]].copy()
            st.markdown("#### 🗂️ Tenanti používající aplikaci " + application_code.strip())
            st.dataframe(
                df_usage,
                width="stretch",
                hide_index=True,
                column_config={
                    'tenantName': st.column_config.TextColumn(label='Název tenanta\n(tenantName)'),
                    'tenantId': st.column_config.TextColumn(label='Id tenanta\n(tenantId)'),
                    'ownerOrgName': st.column_config.TextColumn(label='Název organizace\n(ownerOrgName)'),
                    'ownerOrgCode': st.column_config.TextColumn(label='Kód organizace\n(ownerOrgCode)'),
                    'ownerOrgId': st.column_config.TextColumn(label='Id organizace\n(ownerOrgId)')
                }
            )
        elif application_code.strip():
            st.warning("Pro zadaný Application Code nebyla nalezena žádná data UsageStatistics.")

    with st.expander("🔹 Statistika aplikací používaných tenanty", expanded=False):
        include_smart_check_status = st.checkbox(
            "Zobrazit smart check statusy (Healthy/Degraded/Unhealthy)",
            value=st.session_state['usage_stats_include_smart_check_status'],
            key="usage_stats_include_smart_check_status"
        )

        if st.button("🚀 Načíst statistiku aplikací podle tenantů", key="btn_load_usage_stats_tenants"):
            st.session_state['usage_stats_tenant_app_items'] = []
            with st.spinner("Načítám UsageStatistics tenant-app ..."):
                try:
                    tenant_app_data = fetch_applications_used_by_tenants(
                        st.session_state['credentials']['api_url'],
                        st.session_state['access_token'],
                        st.session_state['credentials']['tenant_id'],
                        include_smart_check_status=include_smart_check_status
                    )
                    if isinstance(tenant_app_data, dict) and 'items' in tenant_app_data:
                        st.session_state['usage_stats_tenant_app_items'] = tenant_app_data['items']
                    elif isinstance(tenant_app_data, list):
                        st.session_state['usage_stats_tenant_app_items'] = tenant_app_data
                    else:
                        st.session_state['usage_stats_tenant_app_items'] = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Načtení statistik aplikací selhalo: {e}")

        if st.session_state['usage_stats_tenant_app_items']:
            df_tenant_apps = pd.DataFrame(st.session_state['usage_stats_tenant_app_items'])
            visible_columns = ['tenantName', 'tenantId', 'ownerOrgName', 'ownerOrgCode', 'ownerOrgId', 'smartCheckStatus', 'smartCheckResultId', 'smartCheckCreatedOn']
            display_columns = [c for c in visible_columns if c in df_tenant_apps.columns]
            if display_columns:
                st.markdown("#### 🗂️ Data použití aplikací podle tenantů")
                st.dataframe(df_tenant_apps[display_columns], width="stretch", hide_index=True)

            if st.session_state['usage_stats_include_smart_check_status']:
                app_rows = []
                for item in st.session_state['usage_stats_tenant_app_items']:
                    applications = item.get('applications') if isinstance(item, dict) else None
                    if isinstance(applications, list):
                        for app in applications:
                            if isinstance(app, dict):
                                app_rows.append({
                                    'applicationCode': app.get('applicationCode'),
                                    'smartCheckStatus': app.get('smartCheckStatus')
                                })
                if app_rows:
                    df_apps = pd.DataFrame(app_rows).dropna(subset=['applicationCode', 'smartCheckStatus'])
                    if not df_apps.empty:
                        status_order = ['Healthy', 'Degraded', 'Unhealthy']
                        df_apps['smartCheckStatus'] = pd.Categorical(df_apps['smartCheckStatus'], categories=status_order, ordered=True)
                        df_apps_grouped = df_apps.groupby(['applicationCode', 'smartCheckStatus']).size().reset_index(name='count')
                        fig = px.bar(
                            df_apps_grouped,
                            x='applicationCode',
                            y='count',
                            color='smartCheckStatus',
                            category_orders={'smartCheckStatus': status_order},
                            labels={'applicationCode': 'Application Code', 'count': 'Počet', 'smartCheckStatus': 'SmartCheck status'},
                            title='SmartCheck statusy aplikací (agregováno přes všechny tenanty)',
                            barmode='group'
                        )
                        fig.update_layout(xaxis_tickangle=-45, xaxis={'categoryorder':'total descending'})
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Žádná data smart check statusů aplikací k zobrazení.")
                else:
                    st.info("Žádná data smart check aplikací k zobrazení.")
            else:
                tenant_app_counts = []
                for item in st.session_state['usage_stats_tenant_app_items']:
                    tenant_name = item.get('tenantName') or item.get('tenantId') or 'Neznámý tenant'
                    applications = item.get('applications') if isinstance(item, dict) else None
                    if isinstance(applications, list):
                        tenant_app_counts.append({
                            'tenant': tenant_name,
                            'app_count': len(applications)
                        })
                if tenant_app_counts:
                    df_tenant_counts = pd.DataFrame(tenant_app_counts)
                    df_tenant_counts = df_tenant_counts.groupby('tenant', as_index=False)['app_count'].sum()
                    fig = px.pie(
                        df_tenant_counts,
                        names='tenant',
                        values='app_count',
                        title='Počet aplikací použitých v rámci jednotlivých tenantů',
                        hole=0.4
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Žádná data o počtech aplikací na tenanta k zobrazení.")
