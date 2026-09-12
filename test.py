import uuid
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

payload = 'scope=GIGACHAT_API_PERS'

headers = {
  'Content-Type': 'application/x-www-form-urlencoded',
  'Accept': 'application/json',
  'RqUID': str(uuid.uuid4()),
  'Authorization': 'Basic MDFhMDcxODgtMzc1Yi03YTVmLWJjMjMtMTVkMzQ4ZTAwNDcxOjg5NjIxMjJkLTg5ZDUtNDczNy1hYTg1LWQwZWEyNzY1MjRlYQ=='
}

response = requests.post(url, headers=headers, data=payload, verify=False)

print(f"Статус ответа: {response.status_code}")
print(f"Тело ответа: {response.text}")