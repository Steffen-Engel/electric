import logging

import modbus_tk.defines as cst

from electric.icharger.models import SystemStorage, WriteDataSegment, OperationResponse, ObjectNotFoundException, BadRequestException
from modbus_usb import iChargerMaster
from models import DeviceInfo, ChannelStatus, Control, PresetIndex, Preset, ReadDataSegment

CHANNEL_INPUT_HEADER_OFFSET = 0
CHANNEL_INPUT_FOOTER_OFFSET = 51
CHANNEL_INPUT_CELL_IR_FORMAT = 35
CHANNEL_INPUT_CELL_BALANCE_OFFSET = 27
CHANNEL_INPUT_CELL_VOLT_OFFSET = 11

# see the helper/main.cpp module I created that tells me these
# offset values more reliably than Mr Blind Man.
SYSTEM_STORAGE_OFFSET_FANS_OFF_DELAY = 5
SYSTEM_STORAGE_OFFSET_CALIBRATION = 22
SYSTEM_STORAGE_OFFSET_CHARGER_POWER = 34

logger = logging.getLogger('electric.app.{0}'.format(__name__))

VALUE_ORDER_LOCK = 0x55aa


class Operation:
    Charge = 0
    Storage = 1
    Discharge = 2
    Cycle = 3
    Balance = 4


class Order:
    Stop = 0
    Run = 1
    Modify = 2
    WriteSys = 3
    WriteMemHead = 4
    WriteMem = 5
    TransLogOn = 6
    TransLogOff = 7
    MsgBoxYes = 8
    MsgBoxNo = 9


class ChargerCommsManager(object):
    """
    The comms manager is responsible for data translation between the MODBUS types and the world outside.  It uses an
    instance of the modbus capable read/write routines to fetch and modify charger parameters.  It co-ordinates
    multiple modbus segment reads/writes where required.

    Validation is not performed here - the data going in/out is assumed to be correct already.
    """
    locking = False

    def __init__(self, master=None):
        if master is None:
            master = iChargerMaster()
        self.charger = master

    def reset(self):
        self.charger.reset()

    def get_device_info(self):
        """
        Returns the following information from the iCharger, known as the 'device only reads message'
        :return: a DeviceInfo instance
        """
        vars = ReadDataSegment(self.charger, "vars", "h12sHHHHHH", base=0x0000)
        return DeviceInfo(vars.data)

    def get_channel_status(self, channel, device_id=None):
        """"
        Returns the following information from the iCharger, known as the 'channel input read only' message:
        :return: ChannelStatus instance
        """
        addr = 0x100 if channel == 0 else 0x200

        # timestamp -> ext temp
        header_fmt = "LlhHHlhh"
        header_data = self.charger.modbus_read_registers(addr, header_fmt)

        # cell 0-15 voltage
        cell_volt_fmt = "16H"
        cell_volt_addr = addr + CHANNEL_INPUT_CELL_VOLT_OFFSET
        cell_volt = self.charger.modbus_read_registers(cell_volt_addr, cell_volt_fmt)

        # cell 0-15 balance
        cell_balance_fmt = "16B"
        cell_balance_addr = addr + CHANNEL_INPUT_CELL_BALANCE_OFFSET
        cell_balance = self.charger.modbus_read_registers(cell_balance_addr, cell_balance_fmt)

        # cell 0-15 IR
        cell_ir_fmt = "16H"
        cell_ir_addr = addr + CHANNEL_INPUT_CELL_IR_FORMAT
        cell_ir = self.charger.modbus_read_registers(cell_ir_addr, cell_ir_fmt)

        # total IR -> dialog box ID
        footer_fmt = "7H"
        footer_addr = addr + CHANNEL_INPUT_FOOTER_OFFSET
        footer = self.charger.modbus_read_registers(footer_addr, footer_fmt)

        return ChannelStatus.modbus(device_id, channel, header_data, cell_volt, cell_balance, cell_ir, footer)

    def get_control_register(self):
        "Returns the current run state of a particular channel"
        return Control(self.charger.modbus_read_registers(0x8000, "7H", function_code=cst.READ_HOLDING_REGISTERS))

    def _beep_summary_dict(self, enabled, volume, type):
        return {
            "enabled": enabled,
            "volume": volume,
            "type": type
        }

    def set_beep_properties(self, beep_index=0, enabled=True, volume=5):
        # for now we only access beep type values
        base = 0x8400

        results = ReadDataSegment(self.charger, "temp", "8H", base=0x8400 + 13)
        value_enabled = list(results.data[:4])
        value_volume = list(results.data[4:])

        value_enabled[beep_index] = int(enabled)
        value_volume[beep_index] = volume

        return self.charger.modbus_write_registers(base + 13, value_enabled + value_volume)

    def set_active_channel(self, channel):
        base = 0x8000 + 2
        if channel not in (0, 1):
            return None
        return self.charger.modbus_write_registers(base, (channel,))

    def get_system_storage(self):
        """Returns the system storage area of the iCharger"""
        # temp-unit -> beep-vol
        ds1 = ReadDataSegment(self.charger, "vars1", "21H", base=0x8400)
        # dump3 -> reg current limit
        ds2 = ReadDataSegment(self.charger, "vars2", "13H", prev_format=ds1)
        # charge/discharge power -> modbus_serial_parity
        ds3 = ReadDataSegment(self.charger, "vars3", "17H", prev_format=ds2)

        return SystemStorage.modbus(ds1, ds2, ds3)

    def save_system_storage(self, system_storage_object):
        (s1, s2, s3, s4, s5, s6) = system_storage_object.to_modbus_data()

        # Write the system data to RAM
        ws1 = self.charger.modbus_write_registers(0x8400, s1)
        ws2 = self.charger.modbus_write_registers(0x8400 + 5, s2)
        ws3 = self.charger.modbus_write_registers(0x8400 + 9, s3)
        ws4 = self.charger.modbus_write_registers(0x8400 + 22, s4)
        ws5 = self.charger.modbus_write_registers(0x8400 + 24, s5)
        ws6 = self.charger.modbus_write_registers(0x8400 + 34, s6)

        # Now write the RAM to flash
        self.take_out_order_lock("save system configuration")
        write_sys_to_flash = (VALUE_ORDER_LOCK, Order.WriteSys, 0, 0,)
        store = self.charger.modbus_write_registers(0x8000 + 3, write_sys_to_flash)
        self.release_order_lock()

        return True

    def select_memory_program(self, memory_slot, channel_number=0):
        self.take_out_order_lock("Selecting memory slot {0}".format(memory_slot))
        (word_count,) = self.charger.modbus_write_registers(0x8000 + 1, (memory_slot, channel_number,))
        self.release_order_lock()
        return word_count

    def save_full_preset_list(self, preset_list):
        (v1, v2) = preset_list.to_modbus_data()

        # Write the thing to RAM. Moo.
        part1 = WriteDataSegment(self.charger, "part1", v1, "H32B", base=0x8800)
        part2 = WriteDataSegment(self.charger, "part2", v2, "32B", prev_format=part1)

        # Write to flash.
        self.take_out_order_lock("save preset index, writing index")
        write_head_to_flash = (VALUE_ORDER_LOCK, Order.WriteMemHead, 0, 0,)
        store = self.charger.modbus_write_registers(0x8000 + 3, write_head_to_flash)
        self.release_order_lock()
        return True

    def get_full_preset_list(self):
        (count,) = self.charger.modbus_read_registers(0x8800, "H", function_code=cst.READ_HOLDING_REGISTERS)

        # There are apparently 64 indexes. Apparently.
        read_a_bit_format = "32B"
        data_1 = self.charger.modbus_read_registers(0x8800 + 1, read_a_bit_format, function_code=cst.READ_HOLDING_REGISTERS)
        data_2 = self.charger.modbus_read_registers(0x8800 + 16, read_a_bit_format, function_code=cst.READ_HOLDING_REGISTERS)
        list_of_all_indexes = list(data_1)
        list_of_all_indexes.extend(list(data_2))
        return PresetIndex.modbus(count, list_of_all_indexes)

    def get_preset(self, memory_slot_number):
        # First, load the indicies and see if in fact this is mapped. If not, don't bother even trying
        preset_index = self.get_full_preset_list()
        if preset_index.index_of_preset_with_memory_slot_number(memory_slot_number) is None:
            message = "No preset is mapped with slot number {0}".format(memory_slot_number)
            raise ObjectNotFoundException(message)

        result = self.select_memory_program(memory_slot_number)

        # use-flag -> channel mode
        vars1 = ReadDataSegment(self.charger, "vars1", "H38sLBB7cHB", base=0x8c00)
        # save to sd -> bal-set-point
        vars2 = ReadDataSegment(self.charger, "vars2", "BHH12BHBBB", prev_format=vars1)
        # bal-delay, keep-charge-enable -> reg discharge mode
        vars3 = ReadDataSegment(self.charger, "vars3", "BB14H", prev_format=vars2)
        # ni-peak -> cycle-delay
        vars4 = ReadDataSegment(self.charger, "vars4", "16H", prev_format=vars3)
        # cycle-mode -> ni-zn-cell
        vars5 = ReadDataSegment(self.charger, "vars5", "B6HB2HB3HB", prev_format=vars4)

        preset = Preset.modbus(memory_slot_number, vars1, vars2, vars3, vars4, vars5)

        # if preset.is_unused:
        #     message = "Preset in slot {0} appears to exist, is marked as unused.".format(memory_slot_number)
        #     raise ObjectNotFoundException(message)

        return preset

    def delete_preset_at_index(self, preset_memory_slot_number):
        # Find this thing, within the index
        preset_index = self.get_full_preset_list()

        index_number = preset_index.index_of_preset_with_memory_slot_number(preset_memory_slot_number)
        if index_number is None:
            message = "Cannot find preset with memory slot {0}".format(preset_memory_slot_number)
            raise ObjectNotFoundException(message)
        logger.info("Remove item at memory slot {0}, index {1}".format(preset_memory_slot_number, index_number))

        # If the preset is marked as "fixed", then the iCharger UI doesn't allow it to be
        # moved or deleted. Reject the request.
        preset = self.get_preset(preset_memory_slot_number)
        preset.verify_can_be_written_or_deleted()

        # If it is the last object, we can adjust the index map only, and ignore (I hope!) the preset itself.
        preset_index.delete_item_at_index(index_number)

        # Change the preset index so that the last item is "unused"
        index_save_result = self.save_full_preset_list(preset_index)

        # Set this preset (slot) used flag to "EMPTY (useflag = 0xffff") in RAM
        logger.info("Setting slot {0} unused flag".format(preset_memory_slot_number))
        self.select_memory_program(preset_memory_slot_number)
        store = self.charger.modbus_write_registers(0x8c00, (0xffff,))

        # Now write back to flash
        self.take_out_order_lock("delete preset, writing preset to flash")
        write_to_flash = (VALUE_ORDER_LOCK, Order.WriteMem, 0, 0,)
        store = self.charger.modbus_write_registers(0x8000 + 3, write_to_flash)
        self.release_order_lock()

        return True

    '''
    This ALWAYS saves a NEW preset. The presets memory_slot is ignored, and it's
    inserted at the end of the preset index list.
    '''

    def add_new_preset(self, preset):
        # Find the next free memory slot, assign that to the preset, and save both indexes + preset
        preset_index = self.get_full_preset_list()

        # This assigns the preset the next available memory slot, and also writes that into
        # the index.
        if not preset_index.add_to_index(preset):
            raise BadRequestException("Presets full")

        # Right. Now we can save it.
        logger.info("Preset Index before add: {0}".format(preset_index.to_native()))
        logger.info("Adding new preset at slot {0}".format(preset.memory_slot))
        self.save_preset_to_memory_slot(preset, preset.memory_slot, verify_write=False)

        # And save the new preset list
        self.save_full_preset_list(preset_index)
        logger.info("Preset Index after add: {0}".format(self.get_full_preset_list().to_native()))

        return self.get_preset(preset.memory_slot)

    '''
    This saves an existing preset to memory.
    It does NOT allocate new presets, or insert them into a preset index list
    '''

    def save_preset_to_memory_slot(self, preset, memory_slot, verify_write=True):
        # We don't want to verify if we're adding. In that case we KNOW we want to add it here.
        # and we want to ignore any older data that may be in that slot.
        if verify_write:
            # Get the preset and verify we can write
            # This has a side effect of self.select_memory_program(memory_slot)
            existing_preset = self.get_preset(memory_slot)
            existing_preset.verify_can_be_written_or_deleted()
        else:
            self.select_memory_program(memory_slot)

        # ask the preset for its data segments
        (v1, v2, v3, v4, v5) = preset.to_modbus_data()

        # Write the preset into the RAM area
        s1 = WriteDataSegment(self.charger, "seg1", v1, "H38sLBB7cHB", base=0x8c00)
        s2 = WriteDataSegment(self.charger, "seg2", v2, "BHH12BHBBB", prev_format=s1)
        s3 = WriteDataSegment(self.charger, "seg3", v3, "BB14H", prev_format=s2)
        s4 = WriteDataSegment(self.charger, "seg4", v4, "16H", prev_format=s3)
        s5 = WriteDataSegment(self.charger, "seg5", v5, "B6HB2HB3HB", prev_format=s4)

        # Now write back to flash
        self.take_out_order_lock("save preset, writing preset to flash")
        write_to_flash = (VALUE_ORDER_LOCK, Order.WriteMem, 0, 0,)
        store = self.charger.modbus_write_registers(0x8000 + 3, write_to_flash)
        self.release_order_lock()

        return True

    def take_out_order_lock(self, message="<unknown reason>"):
        logger.info("Taking out order lock: {0}".format(message))
        self.charger.modbus_write_registers(0x8000 + 3, (VALUE_ORDER_LOCK,))

    def release_order_lock(self):
        # clear the ORDER LOCK value (no idea why - the C++ code does this)
        self.charger.modbus_write_registers(0x8000 + 3, (0,))

    def close_messagebox(self):
        # If showing a dialog, or have error, try to clear the dialog
        self.take_out_order_lock("close messagebox")
        self.charger.modbus_write_registers(0x8000 + 3, (VALUE_ORDER_LOCK, Order.MsgBoxNo, 0, 0,))
        self.release_order_lock()

    def stop_operation(self, channel_number):
        channel_number = min(1, max(0, channel_number))
        values_list = (channel_number, VALUE_ORDER_LOCK, Order.Stop, 0, 0,)

        self.take_out_order_lock("stop")
        modbus_response = self.charger.modbus_write_registers(0x8000 + 2, values_list)
        logger.info("Got back {0} from write".format(modbus_response))
        status = self.get_device_info().get_status(channel_number)
        logger.info("Device status: {0}".format(status.to_native()))
        self.release_order_lock()

        # If showing a dialog, or have error, try to clear the dialog
        # This also works to close the presets listing, if that is open
        if status.dlg_box_status or status.err:
            logger.info("Have dialog showing, attempting to close dialog")
            self.close_messagebox()

        return OperationResponse(modbus_response)

    def run_operation(self, operation, channel_number, preset_memory_slot_index):
        channel_number = min(1, max(0, channel_number))

        # Load the preset from this slot, and check it is valid
        # Loading will itself perform a check for 'used', and will throw an exception it it
        # is not available.
        # It'll also be loaded into RAM.
        logger.info("Begin operation {0} on channel {1} using slot {2}".format(operation, channel_number, preset_memory_slot_index))
        self.get_preset(preset_memory_slot_index)

        self.take_out_order_lock("charging")

        # Translate from a sensible 0..64 index, to where it is in memory
        values_list = (
            operation,
            preset_memory_slot_index,
            channel_number,
            VALUE_ORDER_LOCK,
            Order.Run,
        )

        logger.info("Sending write: {0}".format(values_list))
        modbus_response = self.charger.modbus_write_registers(0x8000, values_list)

        logger.info("Got back {0} from write".format(modbus_response))
        logger.info("Device status: {0}".format(self.get_device_info().get_status(channel_number).to_native()))

        self.release_order_lock()

        return self.get_device_info().get_status(channel_number)
