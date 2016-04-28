__all__ = ['MIMENonMultipart']
from email import errors
from email.mime.base import MIMEBase

class MIMENonMultipart(MIMEBase):
    __qualname__ = 'MIMENonMultipart'

    def attach(self, payload):
        raise errors.MultipartConversionError('Cannot attach additional subparts to non-multipart/*')

