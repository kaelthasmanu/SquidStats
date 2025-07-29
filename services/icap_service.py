""" import os
import tempfile

import icapclient

ICAP_HOST = os.getenv("ICAP_HOST", os.getenv("SQUID_HOST"))
ICAP_PORT = int(os.getenv("ICAP_PORT", 1344))


def scan_file_with_icap(file_storage):
    if file_storage.filename == "":
        return {"error": "No selected file"}, 400

    # Save file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file_storage.save(tmp.name)
        temp_path = tmp.name

    try:
        conn = icapclient.ICAPConnection(ICAP_HOST, port=ICAP_PORT)
        conn.request("REQMOD", temp_path, service="avscan")
        resp = conn.getresponse()
        icap_status = resp.icap_status
        icap_reason = resp.icap_reason
        icap_headers = dict(resp.icap_headers)
        infection = resp.get_icap_header("x-infection-found")
        http_resp_line = getattr(resp, "http_resp_line", None)
        conn.close()

        result = {
            "icap_status": icap_status,
            "icap_reason": icap_reason,
            "icap_headers": icap_headers,
            "http_resp_line": http_resp_line,
            "virus_found": infection is not None,
            "infection_details": infection,
        }
        return result, 200
    except Exception as e:
        return {"error": f"Error scanning file with ICAP: {e}"}, 500
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
 """
