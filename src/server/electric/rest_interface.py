import logging

from flask import request
from flask_restful import Resource, abort
from werkzeug.exceptions import BadRequest

import electric.evil_global as evil_global
from electric.icharger.modbus_usb import connection_state_dict
from icharger.comms_layer import Operation
from icharger.models import Preset, SystemStorage, ObjectNotFoundException

logger = logging.getLogger('electric.app.{0}'.format(__name__))

RETRY_LIMIT = 30


def exclusive(func):
    def wrapper(self, *args, **kwargs):
        with evil_global.lock:
            retry = 0
            while retry < RETRY_LIMIT:
                try:
                    return func(self, *args, **kwargs)

                except BadRequest, badRequest:
                    # Just return it, it's a validation failure
                    raise badRequest
                except ValueError, ve:
                    raise ve
                except ObjectNotFoundException, e:
                    abort(404, message=e.message)

                except Exception, ex:
                    retry += 1

                    logger.warning("{0}/{3}, will try again (count is at {1}/{2})".format(ex, retry, RETRY_LIMIT, type(ex)))

                    evil_global.comms.reset()

                    if retry >= RETRY_LIMIT:
                        logger.warning("retry limit exceeded, aborting the call completely")
                        return connection_state_dict(ex), 504

    return wrapper


class StatusResource(Resource):
    @exclusive
    def get(self):
        info = evil_global.comms.get_device_info()

        evil_global.last_seen_charger_device_id = info.device_id

        obj = info.to_primitive()
        obj.update(connection_state_dict())

        return obj


class ChannelResource(Resource):
    @exclusive
    def get(self, channel_id):
        channel = int(channel_id)
        if not (channel == 0 or channel == 1):
            return connection_state_dict("Channel number must be 0 or 1"), 403

        # yeh, more groan
        status = evil_global.comms.get_channel_status(int(channel), evil_global.last_seen_charger_device_id)

        obj = status.to_primitive()
        obj.update(connection_state_dict())

        return obj


class ControlRegisterResource(Resource):
    @exclusive
    def get(self):
        control = evil_global.comms.get_control_register()

        # note: intentionally no connection state
        return control.to_primitive()


class ChargeResource(ControlRegisterResource):
    @exclusive
    def put(self, channel_id, preset_index):
        operation_response = evil_global.comms.run_operation(Operation.Charge, int(channel_id), int(preset_index)).to_primitive()
        operation_response.update(connection_state_dict())
        return operation_response


class DischargeResource(ControlRegisterResource):
    @exclusive
    def put(self, channel_id, preset_index):
        pass


class BalanceResource(ControlRegisterResource):
    @exclusive
    def put(self, channel_id, preset_index):
        pass


class MeasureIRResource(ControlRegisterResource):
    @exclusive
    def put(self, channel_id):
        pass


class StopResource(ControlRegisterResource):
    @exclusive
    def put(self, channel_id):
        operation_response = evil_global.comms.stop_operation(int(channel_id)).to_primitive()
        operation_response.update(connection_state_dict())
        return operation_response


class SystemStorageResource(Resource):
    @exclusive
    def get(self):
        syst = evil_global.comms.get_system_storage()

        obj = syst.to_primitive()
        obj.update(connection_state_dict())

        return obj

    @exclusive
    def put(self):
        json_dict = request.json
        del json_dict['charger_presence']
        system_storage_object = SystemStorage(json_dict)
        return evil_global.comms.save_system_storage(system_storage_object)


class PresetResource(Resource):
    @exclusive
    def get(self, preset_index):
        preset_index = int(preset_index)
        return evil_global.comms.get_preset(preset_index).to_primitive()

    @exclusive
    def delete(self, preset_index):
        # This will only, I think ... work for "at the end"
        preset_index = int(preset_index)
        logger.info("Try to delete index {0}".format(preset_index))
        return evil_global.comms.delete_preset_at_index(preset_index)

    @exclusive
    def put(self, preset_index):
        preset_index = int(preset_index)
        json_dict = request.json
        logger.info("Asked to save preset to index: {0} with {1}".format(preset_index, json_dict))

        # Turn it into a Preset object
        preset = Preset(json_dict)
        return evil_global.comms.save_preset_to_memory_slot(preset, preset_index)


class PresetListResource(Resource):
    @exclusive
    def get(self):
        preset_list = evil_global.comms.get_full_preset_list()
        # TODO: Error handling

        all_presets = []
        for index in preset_list.range_of_presets():
            preset = evil_global.comms.get_preset(index)

            # TODO: Error handling

            if preset:
                all_presets.append(preset.to_native())

        return all_presets

    @exclusive
    def post(self):
        pass


class PresetOrderResource(Resource):
    @exclusive
    def get(self):
        preset_list = evil_global.comms.get_full_preset_list()
        return preset_list.to_native()

    @exclusive
    def post(self):
        pass
