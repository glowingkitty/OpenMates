import requests
import json
import sys

if len(sys.argv) != 3:
    print("Usage: python revolut_business_register_apple_pay.py <yourSecretApiKey> <your_domain.com>")
    sys.exit(1)

api_key = sys.argv[1]
domain_to_register = sys.argv[2]

url = "https://merchant.revolut.com/api/apple-pay/domains/register"

payload = json.dumps({
  "domain": domain_to_register
})

headers = {
  'Content-Type': 'application/json',
  'Authorization': f'Bearer {api_key}'
}

response = requests.post(url, headers=headers, data=payload)

print(response.text)