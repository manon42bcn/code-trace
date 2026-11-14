class AuthService:
    def login(self, username, password):
        if not username or not password:
            raise ValueError('Missing credentials')
        return self._verify(username, password)

    def _verify(self, username, password):
        return username == 'demo' and password == 'secret'
