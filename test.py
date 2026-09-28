import requests
import json
url = 'https://leetcode.com/graphql'
query = '''
query questionEditorData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    codeSnippets {
      lang
      langSlug
      code
    }
  }
}
'''
variables = {'titleSlug': 'create-a-dataframe-from-list'}
response = requests.post(url, json={'query': query, 'variables': variables})
print(json.dumps(response.json(), indent=2))
