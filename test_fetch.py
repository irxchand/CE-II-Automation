import urllib.request, json
url = 'https://leetcode.com/graphql'
req = urllib.request.Request(url, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
data = json.dumps({
    'query': 'query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { codeSnippets { lang langSlug code } } }',
    'variables': {'titleSlug': 'create-a-dataframe-from-list'}
}).encode('utf-8')
resp = urllib.request.urlopen(req, data)
print(json.dumps(json.loads(resp.read()), indent=2))
