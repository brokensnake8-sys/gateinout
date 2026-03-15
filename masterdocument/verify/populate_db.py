"""
Helper Script: Populate Local Database
Fetch semua member yang punya fingerprint dari API dan simpan ke users.json

Usage:
  python3 populate_db.py <Authorization_token> <client_cookie>
  
Example:
  python3 populate_db.py "Bearer eyJ..." "your_client_cookie_value"
"""

import sys
import requests
import json
import os
from datetime import datetime

API_BASE = "https://machine.haloraga.com/api/v1"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

def fetch_all_members(auth_token: str, auth_client: str):
    """Fetch semua member yang punya fingerprint dari API"""
    headers = {
        "Authorization": auth_token,
        "client": auth_client
    }
    
    try:
        # Endpoint untuk list semua member (sesuaikan dengan API Anda)
        # Ini contoh, mungkin perlu disesuaikan
        resp = requests.get(
            f"{API_BASE}/members",  # atau endpoint lain yang sesuai
            headers=headers,
            timeout=30
        )
        
        if not resp.ok:
            print(f"[ERROR] API returned {resp.status_code}: {resp.text}")
            return []
        
        data = resp.json()
        members = data if isinstance(data, list) else data.get("data", [])
        
        print(f"[INFO] Fetched {len(members)} members from API")
        return members
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch members: {e}")
        return []

def fetch_member_fingerprints(member_id: str, auth_token: str, auth_client: str):
    """Check apakah member punya fingerprint"""
    headers = {
        "Authorization": auth_token,
        "client": auth_client
    }
    
    try:
        resp = requests.get(
            f"{API_BASE}/member-fingerprints/{member_id}",
            headers=headers,
            timeout=10
        )
        
        if resp.ok:
            data = resp.json()
            fingerprints = data if isinstance(data, list) else data.get("data", [])
            return len(fingerprints) > 0
        
        return False
        
    except Exception:
        return False

def populate_database(auth_token: str, auth_client: str):
    """Populate database lokal dengan member yang punya fingerprint"""
    
    print("=" * 60)
    print("POPULATE LOCAL DATABASE")
    print("=" * 60)
    print()
    
    # Fetch all members
    print("[1/3] Fetching members from API...")
    members = fetch_all_members(auth_token, auth_client)
    
    if not members:
        print("[ERROR] No members found or API error")
        return
    
    # Filter members yang punya fingerprint
    print(f"[2/3] Checking fingerprints for {len(members)} members...")
    db = {}
    
    for idx, member in enumerate(members, 1):
        member_id = member.get("id") or member.get("memberId")
        if not member_id:
            continue
        
        print(f"  [{idx}/{len(members)}] Checking {member.get('name', 'unknown')}...", end=" ")
        
        # Check if has fingerprint
        has_fp = fetch_member_fingerprints(member_id, auth_token, auth_client)
        
        if has_fp:
            # Simpan ke database
            # Username format: fpXXXXXXXX (dari member_id)
            sanitized_id = member_id.replace("-", "")
            username = ("fp" + sanitized_id)[:16]  # sesuaikan dengan format di app.py
            
            db[username] = {
                "member_id": member_id,
                "name": member.get("name", "—"),
                "cardNumber": member.get("cardNumber", "—"),
                "packet": member.get("packet", "—"),
                "expDate": member.get("expDate", "—"),
                "last_updated": datetime.now().isoformat()
            }
            print("✓ HAS FINGERPRINT")
        else:
            print("✗ no fingerprint")
    
    # Save to JSON
    print()
    print(f"[3/3] Saving {len(db)} users to {DB_PATH}...")
    
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"[SUCCESS] Database saved! {len(db)} users cached.")
    except Exception as e:
        print(f"[ERROR] Failed to save database: {e}")
    
    print()
    print("=" * 60)
    print("DONE!")
    print("=" * 60)

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 populate_db.py <Authorization_token> <client_cookie>")
        print()
        print("Example:")
        print('  python3 populate_db.py "Bearer eyJ..." "your_client_cookie"')
        sys.exit(1)
    
    auth_token = sys.argv[1]
    auth_client = sys.argv[2]
    
    populate_database(auth_token, auth_client)

if __name__ == "__main__":
    main()
