import requests as rq 

class Simple_LC_Client:
    """注意：此Simple_LC_Client的实现在cookie的传入上与notebook原版有所差异"""
    def process_cookie(self, cookie):
        cookie_temp = cookie.split(';')
        cookie_temp = [i.split('=') for i in cookie_temp]
        cookie_temp = [[i[0], i[1].strip()] for i in cookie_temp]
        return cookie_temp

    def __init__(self, cookie=None):
        self.client = rq.session()
        cookie = self.process_cookie(cookie)
        for cookie_t in cookie:
            name, value = cookie_t
            self.client.cookies.set(name, value)

        # self.client.cookies.set('LEETCODE_SESSION', cookie)
        self.client.encoding = "utf-8"
        self.endpoint = 'https://leetcode.cn/'
        self.headers = {
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.152 Safari/537.36'
        }

    def login(self):
        login_url = 'https://leetcode.cn/accounts/login/?next=%2F'
        login_header = self.headers
        login_header['Referer'] = login_url
        # self.client.get(login_url,verify=False)
        # result = self.client.post(
        #     login_url, headers=login_header,verify=False)

        # result.url 判断是否真正登录成功
        # if result.ok and result.url == self.endpoint:
        #     print("Login successfully!")
        #     return