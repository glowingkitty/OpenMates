
import requests

headers = {
    'Authorization': 'bearer <token>',
}
response = requests.get('http://localhost:1337/api/tasks', headers=headers)


# Print the status code
print(response.status_code)

# Print the response body
print(response.text)