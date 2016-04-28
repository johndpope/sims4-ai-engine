__all__ = ['MIMEApplication']
from email import encoders
from email.mime.nonmultipart import MIMENonMultipart

class MIMEApplication(MIMENonMultipart):
    __qualname__ = 'MIMEApplication'

    def __init__(self, _data, _subtype='octet-stream', _encoder=encoders.encode_base64, **_params):
        if _subtype is None:
            raise TypeError('Invalid application MIME subtype')
        MIMENonMultipart.__init__(self, 'application', _subtype, **_params)
        self.set_payload(_data)
        _encoder(self)

