import time, copy, custom, tools, networking, transactions
# this file explains how we talk to the database. It explains the rules for 
# adding blocks and transactions.
def db_get(n, DB): 
    n = str(n)
    if len(n) == 130: 
        n = tools.pub2addr(n)
        try:
            a = DB['db'].Get(n)
        except:
            db_put(n, {'count':0, 'amount':0}, DB)  # everyone defaults with 
               # having zero money, and having broadcast zero transcations.
            return db_get(n, DB)
    return tools.unpackage(DB['db'].Get(n))

def db_put(key, dic, DB):  
    key = str(key)
    if len(key) == 130: key = tools.pub2addr(key)  # store by pubkey hash instead of 
    # pubkey to defend against theoretical quantum computing attack.
    return DB['db'].Put(key, tools.package(dic))

def db_delete(key, DB): return DB['db'].Delete(str(key))

def count(pubkey, DB):
    # returns the number of transactions that pubkey has broadcast.
    def zeroth_confirmation_txs(pubkey, DB): 
        return len(filter(lambda t: pubkey == t['id'], DB['txs']))
        
    current = db_get(pubkey, DB)['count']
    return current + zeroth_confirmation_txs(pubkey, DB)

def add_tx(tx, DB):
    # Attempt to add a new transaction into the pool.
    tx_check = transactions.tx_check
    def verify_count(tx, txs): return tx['count'] != count(tx['id'], DB)
    
    def tx_type_check(tx, txs): return type(tx) != type({'a':1})
    
    def type_check(tx, txs): 
        return 'type' not in tx or tx['type'] not in tx_check
        
    def too_big_block(tx, txs): 
        return len(tools.package(txs + [tx])) > networking.MAX_MESSAGE_SIZE - 5000
        
    def verify_tx(tx, txs):
        if type_check(tx, txs): return False
        if verify_count(tx, txs): return False
        if too_big_block(tx, txs): return False
        if 'start' in tx and DB['length'] < tx['start']: return False
        if 'end' in tx and DB['length'] > tx['end']: return False
        return tx_check[tx['type']](tx, txs, DB)
        
    if verify_tx(tx, DB['txs']): DB['txs'].append(tx)

targets = {}
times = {}  # stores blocktimes

def recent_blockthings(key, DB, size = 100, length = 0):
    # Grabs info from old blocks.
    if key == 'time': storage = times
    if key == 'target': storage = targets
    
    def get_val(length):
        leng = str(length)
        if not leng in storage: storage[leng] = db_get(leng, DB)[key]
        return storage[leng]
        
    # print('DB: ' +str(DB))
    if length == 0: length = DB['length']
    start = (length - size) if (length - size) >= 0 else 0
    return map(get_val, range(start, length))

def buffer(str):
    # target is supposed to be 64 characters long
    if len(str) < 64: return buffer('0' + str)
    return str

# sum of numbers expressed as hexidecimal strings
def hexSum(a, b): return buffer(str(hex(int(a, 16) + int(b, 16)))[2:-1])

# use double-size for division, to reduce information leakage.
def hexInvert(n): return buffer(str(hex(int('f' * 128, 16) / int(n, 16)))[2:-1])

def target(DB, length = 0):
    # returns the target difficulty at a paticular blocklength.
    inflection = 0.985  # This constant is selected such that the 50 most recent 
                    # blocks count for 1/2 the total weight.
    history_length = 400  # How far back in history do we compute the target from.
    if length == 0: length = DB['length']
    if length < 4: return '0' * 4 + 'f' * 60  # use same difficulty for first few blocks.
    if length <= DB['length']: return targets[str(length)]  # memoized
    
    def targetTimesFloat(target, number): 
        return buffer(str(hex(int(int(target, 16) * number)))[2:-1])
        
    def weights(length): return [inflection ** (length - i) for i in range(length)]
    
    def estimate_target(DB):
        # We are actually interested in the average number of hashes requred
        # to mine a block. number of hashes required is inversely proportional
        # to target. So we average over inverse-targets, and inverse the final
        # answer.
        def sumTargets(l):
            if len(l) < 1: return 0
            while len(l) > 1:
                l = [hexSum(l[0], l[1])] + l[2:]
            return l[0]
            
        targets = recent_blockthings('target', DB, history_length)        
        w = weights(len(targets))
        tw = sum(w)
        targets = map(hexInvert, targets)
        def weighted_multiply(i): return targetTimesFloat(targets[i], w[i] / tw)
        weighted_targets = [weighted_multiply(i) for i in range(len(targets))]
        return hexInvert(sumTargets(weighted_targets))
        
    def estimate_time(DB):
        times = recent_blockthings('time', DB, history_length)
        blocklengths = [times[i] - times[i - 1] for i in range(1, len(times))]
        w = weights(len(blocklengths))  # geometric weighting
        tw = sum(w)  # normalization constant
        return sum([w[i] * blocklengths[i] / tw for i in range(len(blocklengths))])
        
    retarget = estimate_time(DB) / custom.blocktime(length)
    return targetTimesFloat(estimate_target(DB), retarget)

def add_block(block, DB):
    # attempts adding a new block to the blockchain.
    # median is good for weeding out liars, so long as 
    def median(mylist):  # the liars don't have 51% hashpower.
        if len(mylist) < 1: return 0
        return sorted(mylist)[len(mylist) / 2]
        
    def block_check(block, DB):
        if 'error' in block or 'error' in DB: return False
        if type(block) != type({'a':1}): 
            print('type error')
            return False
        # print('DB: ' +str(DB))
        length = copy.deepcopy(DB['length'])
        if int(block['length']) != int(length) + 1: return False
        if block['diffLength'] != hexSum(DB['diffLength'],
                                       hexInvert(block['target'])):
            print('diff length')
            return False
        if length >= 0:
            if tools.det_hash(db_get(length, DB)) != block['prevHash']: 
                return False
        a = copy.deepcopy(block)
        a.pop('nonce')
        if u'target' not in block.keys(): return False
        half_way = {u'nonce':block['nonce'], u'halfHash':tools.det_hash(a)}
        if tools.det_hash(half_way) > block['target']: return False
        if block['target'] != target(DB, block['length']): return False
        earliest = median(recent_blockthings('time', DB))
        if 'time' not in block: return False
        if block['time'] > time.time(): return False
        if block['time'] < earliest: return False
        return True
        
    # print('trying to add block: ' + str(block))
    if block_check(block, DB):
        print('add_block: ' + str(block))
        db_put(block['length'], block, DB)
        DB['length'] = block['length']
        DB['diffLength'] = block['diffLength']
        orphans = DB['txs']
        DB['txs'] = []
        for tx in block['txs']:
            transactions.add_block[tx['type']](tx, DB)
        for tx in orphans:
            add_tx(tx, DB)

def delete_block(DB):
    # removes the most recent block from the blockchain.
    if DB['length'] < 0: return
    try:
        targets.pop(str(length))
        times.pop(str(length))
    except:
        pass
    block = db_get(DB['length'], DB)
    orphans = DB['txs']
    DB['txs'] = []
    for tx in block['txs']:
        orphans.append(tx)
        transactions.delete_block[tx['type']](tx, DB)
    db_delete(DB['length'], DB)
    DB['length'] -= 1
    if DB['length'] == -1: 
        DB['diffLength'] = '0'
    else:
        DB['diffLength'] = db_get(DB['length'], DB)['diffLength']
    for orphan in sorted(orphans, key = lambda x: x['count']):
        add_tx(tx, DB)
