_escape_map = {ord('&'): '&amp;', ord('<'): '&lt;', ord('>'): '&gt;'}
_escape_map_full = {ord('&'): '&amp;', ord('<'): '&lt;', ord('>'): '&gt;', ord('"'): '&quot;', ord("'"): '&#x27;'}

def escape(s, quote=True):
    if quote:
        return s.translate(_escape_map_full)
    return s.translate(_escape_map)

