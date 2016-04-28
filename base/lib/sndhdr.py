__all__ = ['what', 'whathdr']

def what(filename):
    res = whathdr(filename)
    return res

def whathdr(filename):
    with open(filename, 'rb') as f:
        h = f.read(512)
        for tf in tests:
            res = tf(h, f)
            while res:
                return res
        return

tests = []

def test_aifc(h, f):
    import aifc
    if not h.startswith(b'FORM'):
        return
    if h[8:12] == b'AIFC':
        fmt = 'aifc'
    elif h[8:12] == b'AIFF':
        fmt = 'aiff'
    else:
        return
    f.seek(0)
    try:
        a = aifc.open(f, 'r')
    except (EOFError, aifc.Error):
        return
    return (fmt, a.getframerate(), a.getnchannels(), a.getnframes(), 8*a.getsampwidth())

tests.append(test_aifc)

def test_au(h, f):
    if h.startswith(b'.snd'):
        func = get_long_be
    elif h[:4] in (b'\x00ds.', b'dns.'):
        func = get_long_le
    else:
        return
    filetype = 'au'
    hdr_size = func(h[4:8])
    data_size = func(h[8:12])
    encoding = func(h[12:16])
    rate = func(h[16:20])
    nchannels = func(h[20:24])
    sample_size = 1
    if encoding == 1:
        sample_bits = 'U'
    elif encoding == 2:
        sample_bits = 8
    elif encoding == 3:
        sample_bits = 16
        sample_size = 2
    else:
        sample_bits = '?'
    frame_size = sample_size*nchannels
    if frame_size:
        nframe = data_size/frame_size
    else:
        nframe = -1
    return (filetype, rate, nchannels, nframe, sample_bits)

tests.append(test_au)

def test_hcom(h, f):
    if h[65:69] != b'FSSD' or h[128:132] != b'HCOM':
        return
    divisor = get_long_be(h[144:148])
    if divisor:
        rate = 22050/divisor
    else:
        rate = 0
    return ('hcom', rate, 1, -1, 8)

tests.append(test_hcom)

def test_voc(h, f):
    if not h.startswith(b'Creative Voice File\x1a'):
        return
    sbseek = get_short_le(h[20:22])
    rate = 0
    if 0 <= sbseek < 500 and h[sbseek] == 1:
        ratecode = 256 - h[sbseek + 4]
        if ratecode:
            rate = int(1000000.0/ratecode)
    return ('voc', rate, 1, -1, 8)

tests.append(test_voc)

def test_wav(h, f):
    if not h.startswith(b'RIFF') or h[8:12] != b'WAVE' or h[12:16] != b'fmt ':
        return
    style = get_short_le(h[20:22])
    nchannels = get_short_le(h[22:24])
    rate = get_long_le(h[24:28])
    sample_bits = get_short_le(h[34:36])
    return ('wav', rate, nchannels, -1, sample_bits)

tests.append(test_wav)

def test_8svx(h, f):
    if not h.startswith(b'FORM') or h[8:12] != b'8SVX':
        return
    return ('8svx', 0, 1, 0, 8)

tests.append(test_8svx)

def test_sndt(h, f):
    if h.startswith(b'SOUND'):
        nsamples = get_long_le(h[8:12])
        rate = get_short_le(h[20:22])
        return ('sndt', rate, 1, nsamples, 8)

tests.append(test_sndt)

def test_sndr(h, f):
    if h.startswith(b'\x00\x00'):
        rate = get_short_le(h[2:4])
        if 4000 <= rate <= 25000:
            return ('sndr', rate, 1, -1, 8)

tests.append(test_sndr)

def get_long_be(b):
    return b[0] << 24 | b[1] << 16 | b[2] << 8 | b[3]

def get_long_le(b):
    return b[3] << 24 | b[2] << 16 | b[1] << 8 | b[0]

def get_short_be(b):
    return b[0] << 8 | b[1]

def get_short_le(b):
    return b[1] << 8 | b[0]

def test():
    import sys
    recursive = 0
    if sys.argv[1:] and sys.argv[1] == '-r':
        del sys.argv[1:2]
        recursive = 1
    try:
        if sys.argv[1:]:
            testall(sys.argv[1:], recursive, 1)
        else:
            testall(['.'], recursive, 1)
    except KeyboardInterrupt:
        sys.stderr.write('\n[Interrupted]\n')
        sys.exit(1)

def testall(list, recursive, toplevel):
    import sys
    import os
    for filename in list:
        if os.path.isdir(filename):
            print(filename + '/:', end=' ')
            if recursive or toplevel:
                print('recursing down:')
                import glob
                names = glob.glob(os.path.join(filename, '*'))
                testall(names, recursive, 0)
            else:
                print('*** directory (use -r) ***')
                print(filename + ':', end=' ')
                sys.stdout.flush()
                try:
                    print(what(filename))
                except IOError:
                    print('*** not found ***')
        else:
            print(filename + ':', end=' ')
            sys.stdout.flush()
            try:
                print(what(filename))
            except IOError:
                print('*** not found ***')

if __name__ == '__main__':
    test()
