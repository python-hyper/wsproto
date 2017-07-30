class UnsupportedExtension(Exception):
    def __init__(self, message=None):
        super(UnsupportedExtension, self).__init__(message)
