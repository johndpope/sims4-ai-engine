import time
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiSchema
import services
import sims4.core_services
SLEEP_TIME = 0.1
TIMEOUT = int(1/SLEEP_TIME)
command_schema = GsiSchema()
command_schema.add_field('response', label='Response')

@GsiHandler('command', command_schema)
def invoke_command(command=None, zone_id:int=None):
    ready = False
    output_accum = ''
    response = ''

    def _callback(result):
        nonlocal response, ready
        if result:
            response = 'Success<br>' + output_accum
        else:
            response = 'Failure<br>' + output_accum
        ready = True

    if command is not None:

        def _fake_output(s, context=None):
            nonlocal response
            response += '<br>' + s

        connection = services.client_manager().get_first_client()
        sims4.core_services.command_buffer_service().add_command(command, _callback, _fake_output, zone_id, connection.id)
    timeout_counter = 0
    while not ready:
        time.sleep(SLEEP_TIME)
        timeout_counter += 1
        while timeout_counter > TIMEOUT:
            ready = True
            continue
    return {'response': response}

