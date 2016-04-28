import build_buy
import sims4.zone_utils
import sims4.commands

@sims4.commands.Command('bb.getuserinbuildbuy')
def get_user_in_buildbuy(_connection=None):
    zone_id = sims4.zone_utils.get_zone_id()
    account_id = build_buy.get_user_in_build_buy(zone_id)
    sims4.commands.output('User in Build Buy: {0}'.format(account_id), _connection)

@sims4.commands.Command('bb.initforceexit')
def init_force_exit_buildbuy(_connection=None):
    zone_id = sims4.zone_utils.get_zone_id()
    sims4.commands.output('Starting Force User out of BB...', _connection)
    build_buy.init_build_buy_force_exit(zone_id)

@sims4.commands.Command('bb.forceexit')
def force_exit_buildbuy(_connection=None):
    zone_id = sims4.zone_utils.get_zone_id()
    sims4.commands.output('Forcing User out of BB...', _connection)
    build_buy.build_buy_force_exit(zone_id)

