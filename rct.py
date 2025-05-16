from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import WebDriverException # <<< ADDED IMPORT
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException
import websocket
import time
import json
import logging
import traceback
import os 

# --- Configuration ---
GGE_LOGIN_URL_FOR_RCT = "https://empire.goodgamestudios.com/" 
GGE_WEBSOCKET_URL = "wss://ep-live-de1-game.goodgamestudios.com/"
GGE_GAME_WORLD = "EmpireEx_2"

GGE_RECAPTCHA_V3_SITE_KEY = "6Lc7w34oAAAAAFKhfmln41m96VQm4MNqEdpCYm-k" 
GGE_RECAPTCHA_ACTION = "submit"

TEST_USERNAME = "user" # <<< REPLACE
TEST_PASSWORD = "pw" # <<< REPLACE
TEST_BSO_COMMAND = f"%xt%{GGE_GAME_WORLD}%bso%1%{{\"OID\":1002017,\"AMT\":1,\"POID\":1002000}}%"

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (%(funcName)s) %(message)s')
logger = logging.getLogger("GGETestRCT")

# --- Selenium Function to Get reCAPTCHA Token ---
# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (%(funcName)s) %(message)s')
logger = logging.getLogger("GGETestRCT")

# --- Selenium Function to Get reCAPTCHA Token ---
def get_gge_recaptcha_token(quiet=False): 
    logger.info("Versuche, einen GGE reCAPTCHA Token mit Selenium zu erhalten...")
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--window-size=800,600") 
        # options.add_argument("--headless") 
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox") 
        options.add_argument("--disable-dev-shm-usage") 
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        
        try:
            driver = webdriver.Chrome(options=options) 
        except WebDriverException as e_init_driver:
            logger.error(f"ChromeDriver konnte nicht initialisiert werden (automatische Erkennung): {e_init_driver}")
            logger.error("Stellen Sie sicher, dass chromedriver.exe im PATH oder im Skriptverzeichnis ist und zur Chrome-Version passt.")
            return None
        logger.info("ChromeDriver initialisiert.")
        
        driver.get(GGE_LOGIN_URL_FOR_RCT)
        wait = WebDriverWait(driver, 45, poll_frequency=0.1) 

        logger.info("Warte auf Spiel-iFrame (iframe#game)...")
        iframe_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe#game')))
        driver.switch_to.frame(iframe_element)
        logger.info("Zum Spiel-iFrame gewechselt. Warte auf reCAPTCHA Badge (.grecaptcha-badge)...")

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.grecaptcha-badge')))
        logger.info("reCAPTCHA Badge gefunden.")
        
        logger.info("Warte 2 zusätzliche Sekunden, falls Initialisierung noch läuft...")
        time.sleep(2.0)

        logger.info("Führe grecaptcha.execute-Skript aus...")
        script_to_execute = f"""
            return new Promise((resolve, reject) => {{
                if (typeof window.grecaptcha === 'undefined' || typeof window.grecaptcha.ready === 'undefined') {{
                    let err_msg = 'grecaptcha object not ready or not defined!';
                    console.error('[JS] ' + err_msg);
                    reject(err_msg);
                    return;
                }}
                window.grecaptcha.ready(() => {{
                    console.log('[JS] grecaptcha ist bereit. Führe execute aus...');
                    try {{
                        window.grecaptcha.execute('{GGE_RECAPTCHA_V3_SITE_KEY}', {{ action: '{GGE_RECAPTCHA_ACTION}' }})
                            .then(token => {{
                                console.log('[JS] Token erhalten von execute:', token ? token.substring(0,10) + '...' : 'null');
                                resolve(token);
                             }},
                             err => {{
                                 console.error('[JS] grecaptcha.execute promise (inline) rejected:', err);
                                 reject(err ? err.toString() : "Promise rejected with no error");
                             }}
                            )
                           .catch(err => {{ 
                                console.error('[JS] grecaptcha.execute .catch(err) triggered:', err);
                               reject(err ? err.toString() : "Promise caught with no error");
                            }});
                    }} catch (e) {{
                        console.error('[JS] Fehler beim direkten Aufruf von grecaptcha.execute:', e);
                        reject(e.toString());
                    }}
                }});
            }});
        """
        recaptcha_token = driver.execute_script(script_to_execute)
        
        if recaptcha_token:
            logger.info(f"✅ Erfolgreich reCAPTCHA Token erhalten: {recaptcha_token}...")
            return recaptcha_token
        else:
            logger.error("❌ Konnte reCAPTCHA Token nicht abrufen (execute gab null/undefined zurück).")
        
            return None

    except SeleniumTimeoutException as e_timeout:
        logger.error(f"Selenium Timeout beim Warten auf ein Element: {e_timeout}")
        if driver: driver.save_screenshot("selenium_timeout.png")
        if not quiet: traceback.print_exc()
        return None
    except WebDriverException as e_wd: 
        logger.error(f"WebDriver Fehler beim Initialisieren oder Ausführen von Selenium: {e_wd}")
        if not quiet: traceback.print_exc()
        return None
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Abrufen des reCAPTCHA Tokens: {e}")
        if not quiet:
             traceback.print_exc()
        return None 
    finally:
        if driver:
            driver.quit()
        logger.info("Selenium Browser für reCAPTCHA geschlossen.")


def gge_login_sync_worker_with_rct(username, password, rct_token, user_id_for_logging="TestUser"):
    ws = None; connect_timeout = 20.0; login_step_delay = 0.2
    login_confirmation_timeout = 10.0
    individual_recv_timeout = 0.5

    try:
        logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) GGE Login für '{username}'...")
        ws = websocket.create_connection(GGE_WEBSOCKET_URL, timeout=connect_timeout)
        logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) ✅ WebSocket-Verbindung hergestellt!")
        
        try:
            ws.settimeout(2.0) 
            initial_msg = ws.recv()
            logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Initiale Nachricht von GGE: {initial_msg[:100]}")
        except websocket.WebSocketTimeoutException:
            logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Keine initiale Nachricht von GGE innerhalb von 2s.")
        except Exception as e_init_recv:
            logger.warning(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Fehler beim Empfangen initialer Nachricht: {e_init_recv}")
        
        ws.settimeout(connect_timeout)

        logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Sende Login-Sequenz...")
        
        ws.send("<msg t='sys'><body action='verChk' r='0'><ver v='166' /></body></msg>")
        ws.send(f"<msg t='sys'><body action='login' r='0'><login z='{GGE_GAME_WORLD}'><nick><![CDATA[]]></nick><pword><![CDATA[1133015%de%0]]></pword></login></body></msg>") 
        ws.send(f"%xt%{GGE_GAME_WORLD}%vln%1%{{\"NOM\":\"{username}\"}}%")
        
        login_payload = {
            "CONM": 297, "RTM": 54, "ID": 0, "PL": 1, 
            "NOM": username, "PW": password, "LT": None, "LANG": "de", 
            "DID": "0", "AID": "1728606031093813874", "KID": "", 
            "REF": "https://empire.goodgamestudios.com", "GCI": "", 
            "SID": 9, "PLFID": 1, "RCT": rct_token
        }
        login_command = f"%xt%{GGE_GAME_WORLD}%lli%1%{json.dumps(login_payload)}%"
        logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Sende Login Befehl: {login_command}")
        ws.send(login_command)
        login_command_sent_time = time.time()
        
        time.sleep(0.5)
        if not ws.connected: 
            logger.error(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) GGE WS Verbindung direkt nach Senden des Login Befehls verloren."); return None
        
        logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Warte auf Login Bestätigung (%xt%lli%1%0%)...")
        confirmation_found = False
        login_related_messages_snippets = []
        
        while (time.time() - login_command_sent_time) < login_confirmation_timeout:
            if not ws.connected:
                logger.warning(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) WS getrennt während Warten auf Login Bestätigung.")
                break
            
            ws.settimeout(individual_recv_timeout)
            try:
                raw_msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue 
            except Exception as e_inner_recv:
                logger.error(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Innerer recv Fehler: {e_inner_recv}")
                break

            msg_str = ""
            if isinstance(raw_msg, bytes):
                try: msg_str = raw_msg.decode('utf-8')
                except UnicodeDecodeError: msg_str = str(raw_msg)
            elif isinstance(raw_msg, str): msg_str = raw_msg
            else: msg_str = str(raw_msg)

            login_related_messages_snippets.append(msg_str[:200])
            
            if "%xt%lli%1%0%" in msg_str:
                logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) ✅ Login Bestätigung (%xt%lli%1%0%) erhalten!")
                confirmation_found = True
                break
        
        if login_related_messages_snippets:
            logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Nachrichten-Snippets während Login-Bestätigungswartezeit: {login_related_messages_snippets}")
        
        if confirmation_found:
            logger.info(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Login bestätigt. Verwerfe weitere Nachrichten für 1 Sekunde...")
            discard_start_time = time.time()
            try:
                ws.settimeout(0.1) 
                while time.time() - discard_start_time < 1.0:
                    if not ws.connected: break
                    ws.recv() 
            except websocket.WebSocketTimeoutException: pass 
            except Exception as e_discard: logger.warning(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Fehler beim Verwerfen von Nachrichten nach lli%0: {e_discard}")
            
            ws.settimeout(connect_timeout) 
            return ws 
        else:
            logger.error(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Login Bestätigung (%xt%lli%1%0%) NICHT innerhalb {login_confirmation_timeout}s erhalten.")
            if ws.connected: ws.close()
            return None

    except Exception as e_main: 
        logger.error(f"[Benutzer:{user_id_for_logging}] (SyncWorker-RCT) Unerwarteter GGE Login Fehler: {e_main}", exc_info=True)
    
    if ws:
        try:
            if ws.connected: ws.close()
        except: pass
    return None

# --- Main Test ---
if __name__ == "__main__":
    logger.info("Starte Testskript für reCAPTCHA Token, Login und BSO Befehl.")

    if TEST_USERNAME == "YourTestUsername" or TEST_PASSWORD == "YourTestPassword":
        logger.error("Bitte aktualisieren Sie TEST_USERNAME und TEST_PASSWORD im Skript mit echten Testdaten.")
        exit()
        
    rct = get_gge_recaptcha_token()

    if not rct:
        logger.error("Konnte keinen reCAPTCHA Token erhalten. Test wird abgebrochen.")
        exit()
    
    logger.info(f"ReCAPTCHA Token für Test: {rct[:60]}...")
    
    gge_ws = gge_login_sync_worker_with_rct(TEST_USERNAME, TEST_PASSWORD, rct)

    if gge_ws and gge_ws.connected:
        logger.info("✅ GGE Login mit RCT erfolgreich! WebSocket ist verbunden.")
        logger.info("Warte 2 Sekunden vor dem Senden des BSO Befehls...")
        time.sleep(2)
        logger.info(f"Sende BSO Befehl: {TEST_BSO_COMMAND}")
        try:
            gge_ws.send(TEST_BSO_COMMAND)
            logger.info("BSO Befehl gesendet. Warte auf Antworten...")
            
            gge_ws.settimeout(5.0); bso_responses = []
            try:
                for _ in range(5): 
                    if not gge_ws.connected: break
                    response_raw = gge_ws.recv()
                    response_str = response_raw.decode('utf-8') if isinstance(response_raw, bytes) else str(response_raw)
                    bso_responses.append(response_str[:200])
                    logger.info(f"<-- Antwort auf BSO?: {response_str[:200]}")
            except websocket.WebSocketTimeoutException: logger.info("Keine weiteren direkten Antworten auf BSO innerhalb des Timeouts.")
            except Exception as e_bso_recv: logger.error(f"Fehler beim Empfangen der BSO Antwort: {e_bso_recv}")
            
            if bso_responses: logger.info(f"Empfangene Nachrichten nach BSO (Auszug): {bso_responses}")

        except Exception as e_send_bso:
            logger.error(f"Fehler beim Senden des BSO Befehls: {e_send_bso}")
        finally:
            if gge_ws.connected:
                logger.info("Schließe GGE WebSocket Verbindung.")
                gge_ws.close()
    else:
        logger.error("❌ GGE Login mit RCT ist fehlgeschlagen. BSO Befehl nicht gesendet.")
    logger.info("Testskript beendet.")