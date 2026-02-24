import requests, json
headers={'X-TBA-Auth-Key':'hae7pfixkaYpROTHhMx6XQ5qLkjT5v7jX7IymIp3sFadVOTsboxkSVJlYu4yoq9a'}
url='https://www.thebluealliance.com/api/v3/event/2026week0/matches'
try:
    resp=requests.get(url, headers=headers, timeout=30)
    print('status', resp.status_code)
    jm=resp.json()
    print('len', len(jm))
    for m in jm:
        print(m.get('key'), m.get('comp_level'), m.get('set_number'), m.get('match_number'))
except Exception as e:
    print('error', e)
