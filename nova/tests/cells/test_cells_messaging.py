# Copyright (c) 2012 Rackspace Hosting # All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Tests For Cells Messaging module
"""
from nova.cells import messaging
from nova.cells import utils as cells_utils
from nova import context
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import rpc
from nova.openstack.common import timeutils
from nova import test
from nova.tests.cells import fakes


CONF = cfg.CONF
CONF.import_opt('name', 'nova.cells.opts', group='cells')
CONF.import_opt('allowed_rpc_exception_modules',
                'nova.openstack.common.rpc')


class CellsMessageClassesTestCase(test.TestCase):
    """Test case for the main Cells Message classes."""
    def setUp(self):
        super(CellsMessageClassesTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        # Need to be able to deserialize test.TestingException.
        allowed_modules = CONF.allowed_rpc_exception_modules
        allowed_modules.append('nova.test')
        self.flags(allowed_rpc_exception_modules=allowed_modules)
        self.our_name = 'api-cell'
        self.msg_runner = fakes.get_message_runner(self.our_name)
        self.state_manager = self.msg_runner.state_manager

    def test_reverse_path(self):
        path = 'a!b!c!d'
        expected = 'd!c!b!a'
        rev_path = messaging._reverse_path(path)
        self.assertEqual(rev_path, expected)

    def test_response_cell_name_from_path(self):
        # test array with tuples of inputs/expected outputs
        test_paths = [('cell1', 'cell1'),
                      ('cell1!cell2', 'cell2!cell1'),
                      ('cell1!cell2!cell3', 'cell3!cell2!cell1')]

        for test_input, expected_output in test_paths:
            self.assertEqual(expected_output,
                    messaging._response_cell_name_from_path(test_input))

    def test_response_cell_name_from_path_neighbor_only(self):
        # test array with tuples of inputs/expected outputs
        test_paths = [('cell1', 'cell1'),
                      ('cell1!cell2', 'cell2!cell1'),
                      ('cell1!cell2!cell3', 'cell3!cell2')]

        for test_input, expected_output in test_paths:
            self.assertEqual(expected_output,
                    messaging._response_cell_name_from_path(test_input,
                            neighbor_only=True))

    def test_targeted_message(self):
        self.flags(max_hop_count=99, group='cells')
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual(self.ctxt, tgt_message.ctxt)
        self.assertEqual(method, tgt_message.method_name)
        self.assertEqual(method_kwargs, tgt_message.method_kwargs)
        self.assertEqual(direction, tgt_message.direction)
        self.assertEqual(target_cell, target_cell)
        self.assertFalse(tgt_message.fanout)
        self.assertFalse(tgt_message.need_response)
        self.assertEqual(self.our_name, tgt_message.routing_path)
        self.assertEqual(1, tgt_message.hop_count)
        self.assertEqual(99, tgt_message.max_hop_count)
        self.assertFalse(tgt_message.is_broadcast)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        child_cell = self.state_manager.get_child_cell('child-cell2')
        self.assertEqual(child_cell, next_hop)

    def test_create_targeted_message_with_response(self):
        self.flags(max_hop_count=99, group='cells')
        our_name = 'child-cell1'
        target_cell = 'child-cell1!api-cell'
        msg_runner = fakes.get_message_runner(our_name)
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        tgt_message = messaging._TargetedMessage(msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        self.assertEqual(self.ctxt, tgt_message.ctxt)
        self.assertEqual(method, tgt_message.method_name)
        self.assertEqual(method_kwargs, tgt_message.method_kwargs)
        self.assertEqual(direction, tgt_message.direction)
        self.assertEqual(target_cell, target_cell)
        self.assertFalse(tgt_message.fanout)
        self.assertTrue(tgt_message.need_response)
        self.assertEqual(our_name, tgt_message.routing_path)
        self.assertEqual(1, tgt_message.hop_count)
        self.assertEqual(99, tgt_message.max_hop_count)
        self.assertFalse(tgt_message.is_broadcast)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        parent_cell = msg_runner.state_manager.get_parent_cell('api-cell')
        self.assertEqual(parent_cell, next_hop)

    def test_targeted_message_when_target_is_cell_state(self):
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        target_cell = self.state_manager.get_child_cell('child-cell2')
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual('api-cell!child-cell2', tgt_message.target_cell)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        self.assertEqual(target_cell, next_hop)

    def test_targeted_message_when_target_cell_state_is_me(self):
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        target_cell = self.state_manager.get_my_state()
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual('api-cell', tgt_message.target_cell)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        self.assertEqual(target_cell, next_hop)

    def test_create_broadcast_message(self):
        self.flags(max_hop_count=99, group='cells')
        self.flags(name='api-cell', max_hop_count=99, group='cells')
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction)
        self.assertEqual(self.ctxt, bcast_message.ctxt)
        self.assertEqual(method, bcast_message.method_name)
        self.assertEqual(method_kwargs, bcast_message.method_kwargs)
        self.assertEqual(direction, bcast_message.direction)
        self.assertFalse(bcast_message.fanout)
        self.assertFalse(bcast_message.need_response)
        self.assertEqual(self.our_name, bcast_message.routing_path)
        self.assertEqual(1, bcast_message.hop_count)
        self.assertEqual(99, bcast_message.max_hop_count)
        self.assertTrue(bcast_message.is_broadcast)
        # Correct next hops?
        next_hops = bcast_message._get_next_hops()
        child_cells = self.state_manager.get_child_cells()
        self.assertEqual(child_cells, next_hops)

    def test_create_broadcast_message_with_response(self):
        self.flags(max_hop_count=99, group='cells')
        our_name = 'child-cell1'
        msg_runner = fakes.get_message_runner(our_name)
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        bcast_message = messaging._BroadcastMessage(msg_runner, self.ctxt,
                method, method_kwargs, direction, need_response=True)
        self.assertEqual(self.ctxt, bcast_message.ctxt)
        self.assertEqual(method, bcast_message.method_name)
        self.assertEqual(method_kwargs, bcast_message.method_kwargs)
        self.assertEqual(direction, bcast_message.direction)
        self.assertFalse(bcast_message.fanout)
        self.assertTrue(bcast_message.need_response)
        self.assertEqual(our_name, bcast_message.routing_path)
        self.assertEqual(1, bcast_message.hop_count)
        self.assertEqual(99, bcast_message.max_hop_count)
        self.assertTrue(bcast_message.is_broadcast)
        # Correct next hops?
        next_hops = bcast_message._get_next_hops()
        parent_cells = msg_runner.state_manager.get_parent_cells()
        self.assertEqual(parent_cells, next_hops)

    def test_self_targeted_message(self):
        target_cell = 'api-cell'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'api-cell', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_child_targeted_message(self):
        target_cell = 'api-cell!child-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'child-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_grandchild_targeted_message(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_grandchild_targeted_message_with_response(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs
            return 'our_fake_response'

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])
        self.assertFalse(response.failure)
        self.assertTrue(response.value_or_raise(), 'our_fake_response')

    def test_grandchild_targeted_message_with_error(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('this should be returned')

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(test.TestingException, response.value_or_raise)

    def test_grandchild_targeted_message_max_hops(self):
        self.flags(max_hop_count=2, group='cells')
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('should not be reached')

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellMaxHopCountReached,
                response.value_or_raise)

    def test_targeted_message_invalid_cell(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell4'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellRoutingInconsistency,
                response.value_or_raise)

    def test_targeted_message_invalid_cell2(self):
        target_cell = 'unknown-cell!child-cell2'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellRoutingInconsistency,
                response.value_or_raise)

    def test_broadcast_routing(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True)
        bcast_message.process()
        # fakes creates 8 cells (including ourself).
        self.assertEqual(len(cells), 8)

    def test_broadcast_routing_up(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        msg_runner = fakes.get_message_runner('grandchild-cell3')

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(msg_runner, self.ctxt,
                                                    method, method_kwargs,
                                                    direction,
                                                    run_locally=True)
        bcast_message.process()
        # Paths are reversed, since going 'up'
        expected = set(['grandchild-cell3', 'grandchild-cell3!child-cell3',
                        'grandchild-cell3!child-cell3!api-cell'])
        self.assertEqual(expected, cells)

    def test_broadcast_routing_without_ourselves(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=False)
        bcast_message.process()
        # fakes creates 8 cells (including ourself).  So we should see
        # only 7 here.
        self.assertEqual(len(cells), 7)

    def test_broadcast_routing_with_response(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(len(responses), 8)
        for response in responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

    def test_broadcast_routing_with_response_max_hops(self):
        self.flags(max_hop_count=2, group='cells')
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        # Should only get responses from our immediate children (and
        # ourselves)
        self.assertEqual(len(responses), 5)
        for response in responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

    def test_broadcast_routing_with_all_erroring(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('fake failure')

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(len(responses), 8)
        for response in responses:
            self.assertTrue(response.failure)
            self.assertRaises(test.TestingException, response.value_or_raise)

    def test_broadcast_routing_with_two_erroring(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method_failing(message, **kwargs):
            raise test.TestingException('fake failure')

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)
        fakes.stub_bcast_method(self, 'child-cell2', 'our_fake_method',
                                our_fake_method_failing)
        fakes.stub_bcast_method(self, 'grandchild-cell3', 'our_fake_method',
                                our_fake_method_failing)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(len(responses), 8)
        failure_responses = [resp for resp in responses if resp.failure]
        success_responses = [resp for resp in responses if not resp.failure]
        self.assertEqual(len(failure_responses), 2)
        self.assertEqual(len(success_responses), 6)

        for response in success_responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

        for response in failure_responses:
            self.assertIn(response.cell_name, ['api-cell!child-cell2',
                    'api-cell!child-cell3!grandchild-cell3'])
            self.assertTrue(response.failure)
            self.assertRaises(test.TestingException, response.value_or_raise)


class CellsTargetedMethodsTestCase(test.TestCase):
    """Test case for _TargetedMessageMethods class.  Most of these
    tests actually test the full path from the MessageRunner through
    to the functionality of the message method.  Hits 2 birds with 1
    stone, even though it's a little more than a unit test.
    """
    def setUp(self):
        super(CellsTargetedMethodsTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self._setup_attrs('api-cell', 'api-cell!child-cell2')

    def _setup_attrs(self, source_cell, target_cell):
        self.tgt_cell_name = target_cell
        self.src_msg_runner = fakes.get_message_runner(source_cell)
        self.src_state_manager = self.src_msg_runner.state_manager
        tgt_shortname = target_cell.split('!')[-1]
        self.tgt_cell_mgr = fakes.get_cells_manager(tgt_shortname)
        self.tgt_msg_runner = self.tgt_cell_mgr.msg_runner
        self.tgt_scheduler = self.tgt_msg_runner.scheduler
        self.tgt_state_manager = self.tgt_msg_runner.state_manager
        methods_cls = self.tgt_msg_runner.methods_by_type['targeted']
        self.tgt_methods_cls = methods_cls
        self.tgt_compute_api = methods_cls.compute_api
        self.tgt_db_inst = methods_cls.db

    def test_schedule_run_instance(self):
        host_sched_kwargs = {'filter_properties': {},
                             'key1': 'value1',
                             'key2': 'value2'}
        self.mox.StubOutWithMock(self.tgt_scheduler, 'run_instance')
        self.tgt_scheduler.run_instance(self.ctxt, host_sched_kwargs)
        self.mox.ReplayAll()
        self.src_msg_runner.schedule_run_instance(self.ctxt,
                                                  self.tgt_cell_name,
                                                  host_sched_kwargs)

    def test_run_compute_api_method(self):

        instance_uuid = 'fake_instance_uuid'
        method_info = {'method': 'reboot',
                       'method_args': (instance_uuid, 2, 3),
                       'method_kwargs': {'arg1': 'val1', 'arg2': 'val2'}}
        self.mox.StubOutWithMock(self.tgt_compute_api, 'reboot')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'instance_get_by_uuid')

        self.tgt_db_inst.instance_get_by_uuid(self.ctxt,
                instance_uuid).AndReturn('fake_instance')
        self.tgt_compute_api.reboot(self.ctxt, 'fake_instance', 2, 3,
                arg1='val1', arg2='val2').AndReturn('fake_result')
        self.mox.ReplayAll()

        response = self.src_msg_runner.run_compute_api_method(
                self.ctxt,
                self.tgt_cell_name,
                method_info,
                True)
        result = response.value_or_raise()
        self.assertEqual('fake_result', result)

    def test_run_compute_api_method_unknown_instance(self):
        # Unknown instance should send a broadcast up that instance
        # is gone.
        instance_uuid = 'fake_instance_uuid'
        instance = {'uuid': instance_uuid}
        method_info = {'method': 'reboot',
                       'method_args': (instance_uuid, 2, 3),
                       'method_kwargs': {'arg1': 'val1', 'arg2': 'val2'}}

        self.mox.StubOutWithMock(self.tgt_db_inst, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_destroy_at_top')

        self.tgt_db_inst.instance_get_by_uuid(self.ctxt,
                'fake_instance_uuid').AndRaise(
                exception.InstanceNotFound(instance_id=instance_uuid))
        self.tgt_msg_runner.instance_destroy_at_top(self.ctxt, instance)

        self.mox.ReplayAll()

        response = self.src_msg_runner.run_compute_api_method(
                self.ctxt,
                self.tgt_cell_name,
                method_info,
                True)
        self.assertRaises(exception.InstanceNotFound,
                          response.value_or_raise)

    def test_update_capabilities(self):
        # Route up to API
        self._setup_attrs('child-cell2', 'child-cell2!api-cell')
        capabs = {'cap1': set(['val1', 'val2']),
                  'cap2': set(['val3'])}
        # The list(set([])) seems silly, but we can't assume the order
        # of the list... This behavior should match the code we're
        # testing... which is check that a set was converted to a list.
        expected_capabs = {'cap1': list(set(['val1', 'val2'])),
                           'cap2': ['val3']}
        self.mox.StubOutWithMock(self.src_state_manager,
                                 'get_our_capabilities')
        self.mox.StubOutWithMock(self.tgt_state_manager,
                                 'update_cell_capabilities')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'tell_parents_our_capabilities')
        self.src_state_manager.get_our_capabilities().AndReturn(capabs)
        self.tgt_state_manager.update_cell_capabilities('child-cell2',
                                                        expected_capabs)
        self.tgt_msg_runner.tell_parents_our_capabilities(self.ctxt)

        self.mox.ReplayAll()

        self.src_msg_runner.tell_parents_our_capabilities(self.ctxt)

    def test_update_capacities(self):
        self._setup_attrs('child-cell2', 'child-cell2!api-cell')
        capacs = 'fake_capacs'
        self.mox.StubOutWithMock(self.src_state_manager,
                                 'get_our_capacities')
        self.mox.StubOutWithMock(self.tgt_state_manager,
                                 'update_cell_capacities')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'tell_parents_our_capacities')
        self.src_state_manager.get_our_capacities().AndReturn(capacs)
        self.tgt_state_manager.update_cell_capacities('child-cell2',
                                                      capacs)
        self.tgt_msg_runner.tell_parents_our_capacities(self.ctxt)

        self.mox.ReplayAll()

        self.src_msg_runner.tell_parents_our_capacities(self.ctxt)

    def test_announce_capabilities(self):
        self._setup_attrs('api-cell', 'api-cell!child-cell1')
        # To make this easier to test, make us only have 1 child cell.
        cell_state = self.src_state_manager.child_cells['child-cell1']
        self.src_state_manager.child_cells = {'child-cell1': cell_state}

        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'tell_parents_our_capabilities')
        self.tgt_msg_runner.tell_parents_our_capabilities(self.ctxt)

        self.mox.ReplayAll()

        self.src_msg_runner.ask_children_for_capabilities(self.ctxt)

    def test_announce_capacities(self):
        self._setup_attrs('api-cell', 'api-cell!child-cell1')
        # To make this easier to test, make us only have 1 child cell.
        cell_state = self.src_state_manager.child_cells['child-cell1']
        self.src_state_manager.child_cells = {'child-cell1': cell_state}

        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'tell_parents_our_capacities')
        self.tgt_msg_runner.tell_parents_our_capacities(self.ctxt)

        self.mox.ReplayAll()

        self.src_msg_runner.ask_children_for_capacities(self.ctxt)

    def test_service_get_by_compute_host(self):
        fake_host_name = 'fake-host-name'

        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'service_get_by_compute_host')

        self.tgt_db_inst.service_get_by_compute_host(self.ctxt,
                fake_host_name).AndReturn('fake-service')
        self.mox.ReplayAll()

        response = self.src_msg_runner.service_get_by_compute_host(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name)
        result = response.value_or_raise()
        self.assertEqual('fake-service', result)

    def test_proxy_rpc_to_manager_call(self):
        fake_topic = 'fake-topic'
        fake_rpc_message = 'fake-rpc-message'
        fake_host_name = 'fake-host-name'

        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'service_get_by_compute_host')
        self.mox.StubOutWithMock(rpc, 'call')

        self.tgt_db_inst.service_get_by_compute_host(self.ctxt,
                                                     fake_host_name)
        rpc.call(self.ctxt, fake_topic,
                 fake_rpc_message, timeout=5).AndReturn('fake_result')

        self.mox.ReplayAll()

        response = self.src_msg_runner.proxy_rpc_to_manager(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name,
                fake_topic,
                fake_rpc_message, True, timeout=5)
        result = response.value_or_raise()
        self.assertEqual('fake_result', result)

    def test_proxy_rpc_to_manager_cast(self):
        fake_topic = 'fake-topic'
        fake_rpc_message = 'fake-rpc-message'
        fake_host_name = 'fake-host-name'

        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'service_get_by_compute_host')
        self.mox.StubOutWithMock(rpc, 'cast')

        self.tgt_db_inst.service_get_by_compute_host(self.ctxt,
                                                     fake_host_name)
        rpc.cast(self.ctxt, fake_topic, fake_rpc_message)

        self.mox.ReplayAll()

        self.src_msg_runner.proxy_rpc_to_manager(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name,
                fake_topic,
                fake_rpc_message, False, timeout=None)

    def test_task_log_get_all_targetted(self):
        task_name = 'fake_task_name'
        begin = 'fake_begin'
        end = 'fake_end'
        host = 'fake_host'
        state = 'fake_state'

        self.mox.StubOutWithMock(self.tgt_db_inst, 'task_log_get_all')
        self.tgt_db_inst.task_log_get_all(self.ctxt, task_name,
                begin, end, host=host,
                state=state).AndReturn(['fake_result'])

        self.mox.ReplayAll()

        response = self.src_msg_runner.task_log_get_all(self.ctxt,
                self.tgt_cell_name, task_name, begin, end, host=host,
                state=state)
        self.assertTrue(isinstance(response, list))
        self.assertEqual(1, len(response))
        result = response[0].value_or_raise()
        self.assertEqual(['fake_result'], result)

    def test_compute_node_get(self):
        compute_id = 'fake-id'
        self.mox.StubOutWithMock(self.tgt_db_inst, 'compute_node_get')
        self.tgt_db_inst.compute_node_get(self.ctxt,
                compute_id).AndReturn('fake_result')

        self.mox.ReplayAll()

        response = self.src_msg_runner.compute_node_get(self.ctxt,
                self.tgt_cell_name, compute_id)
        result = response.value_or_raise()
        self.assertEqual('fake_result', result)


class CellsBroadcastMethodsTestCase(test.TestCase):
    """Test case for _BroadcastMessageMethods class.  Most of these
    tests actually test the full path from the MessageRunner through
    to the functionality of the message method.  Hits 2 birds with 1
    stone, even though it's a little more than a unit test.
    """

    def setUp(self):
        super(CellsBroadcastMethodsTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self._setup_attrs()

    def _setup_attrs(self, up=True):
        mid_cell = 'child-cell2'
        if up:
            src_cell = 'grandchild-cell1'
            tgt_cell = 'api-cell'
        else:
            src_cell = 'api-cell'
            tgt_cell = 'grandchild-cell1'

        self.src_msg_runner = fakes.get_message_runner(src_cell)
        methods_cls = self.src_msg_runner.methods_by_type['broadcast']
        self.src_methods_cls = methods_cls
        self.src_db_inst = methods_cls.db
        self.src_compute_api = methods_cls.compute_api

        if not up:
            # fudge things so we only have 1 child to broadcast to
            state_manager = self.src_msg_runner.state_manager
            for cell in state_manager.get_child_cells():
                if cell.name != 'child-cell2':
                    del state_manager.child_cells[cell.name]

        self.mid_msg_runner = fakes.get_message_runner(mid_cell)
        methods_cls = self.mid_msg_runner.methods_by_type['broadcast']
        self.mid_methods_cls = methods_cls
        self.mid_db_inst = methods_cls.db
        self.mid_compute_api = methods_cls.compute_api

        self.tgt_msg_runner = fakes.get_message_runner(tgt_cell)
        methods_cls = self.tgt_msg_runner.methods_by_type['broadcast']
        self.tgt_methods_cls = methods_cls
        self.tgt_db_inst = methods_cls.db
        self.tgt_compute_api = methods_cls.compute_api

    def test_at_the_top(self):
        self.assertTrue(self.tgt_methods_cls._at_the_top())
        self.assertFalse(self.mid_methods_cls._at_the_top())
        self.assertFalse(self.src_methods_cls._at_the_top())

    def test_instance_update_at_top(self):
        fake_info_cache = {'id': 1,
                           'instance': 'fake_instance',
                           'other': 'moo'}
        fake_sys_metadata = [{'id': 1,
                              'key': 'key1',
                              'value': 'value1'},
                             {'id': 2,
                              'key': 'key2',
                              'value': 'value2'}]
        fake_instance = {'id': 2,
                         'uuid': 'fake_uuid',
                         'security_groups': 'fake',
                         'instance_type': 'fake',
                         'volumes': 'fake',
                         'cell_name': 'fake',
                         'name': 'fake',
                         'metadata': 'fake',
                         'info_cache': fake_info_cache,
                         'system_metadata': fake_sys_metadata,
                         'other': 'meow'}
        expected_sys_metadata = {'key1': 'value1',
                                 'key2': 'value2'}
        expected_info_cache = {'other': 'moo'}
        expected_cell_name = 'api-cell!child-cell2!grandchild-cell1'
        expected_instance = {'system_metadata': expected_sys_metadata,
                             'cell_name': expected_cell_name,
                             'other': 'meow',
                             'uuid': 'fake_uuid'}

        # To show these should not be called in src/mid-level cell
        self.mox.StubOutWithMock(self.src_db_inst, 'instance_update')
        self.mox.StubOutWithMock(self.src_db_inst,
                                 'instance_info_cache_update')
        self.mox.StubOutWithMock(self.mid_db_inst, 'instance_update')
        self.mox.StubOutWithMock(self.mid_db_inst,
                                 'instance_info_cache_update')

        self.mox.StubOutWithMock(self.tgt_db_inst, 'instance_update')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'instance_info_cache_update')
        self.tgt_db_inst.instance_update(self.ctxt, 'fake_uuid',
                                         expected_instance,
                                         update_cells=False)
        self.tgt_db_inst.instance_info_cache_update(self.ctxt, 'fake_uuid',
                                                    expected_info_cache,
                                                    update_cells=False)
        self.mox.ReplayAll()

        self.src_msg_runner.instance_update_at_top(self.ctxt, fake_instance)

    def test_instance_destroy_at_top(self):
        fake_instance = {'uuid': 'fake_uuid'}

        # To show these should not be called in src/mid-level cell
        self.mox.StubOutWithMock(self.src_db_inst, 'instance_destroy')

        self.mox.StubOutWithMock(self.tgt_db_inst, 'instance_destroy')
        self.tgt_db_inst.instance_destroy(self.ctxt, 'fake_uuid',
                                 update_cells=False)
        self.mox.ReplayAll()

        self.src_msg_runner.instance_destroy_at_top(self.ctxt, fake_instance)

    def test_instance_hard_delete_everywhere(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        instance = {'uuid': 'meow'}

        # Should not be called in src (API cell)
        self.mox.StubOutWithMock(self.src_compute_api, 'delete')

        self.mox.StubOutWithMock(self.mid_compute_api, 'delete')
        self.mox.StubOutWithMock(self.tgt_compute_api, 'delete')

        self.mid_compute_api.delete(self.ctxt, instance)
        self.tgt_compute_api.delete(self.ctxt, instance)

        self.mox.ReplayAll()

        self.src_msg_runner.instance_delete_everywhere(self.ctxt,
                instance, 'hard')

    def test_instance_soft_delete_everywhere(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        instance = {'uuid': 'meow'}

        # Should not be called in src (API cell)
        self.mox.StubOutWithMock(self.src_compute_api, 'soft_delete')

        self.mox.StubOutWithMock(self.mid_compute_api, 'soft_delete')
        self.mox.StubOutWithMock(self.tgt_compute_api, 'soft_delete')

        self.mid_compute_api.soft_delete(self.ctxt, instance)
        self.tgt_compute_api.soft_delete(self.ctxt, instance)

        self.mox.ReplayAll()

        self.src_msg_runner.instance_delete_everywhere(self.ctxt,
                instance, 'soft')

    def test_instance_fault_create_at_top(self):
        fake_instance_fault = {'id': 1,
                               'other stuff': 2,
                               'more stuff': 3}
        expected_instance_fault = {'other stuff': 2,
                                   'more stuff': 3}

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst, 'instance_fault_create')
        self.mox.StubOutWithMock(self.mid_db_inst, 'instance_fault_create')

        self.mox.StubOutWithMock(self.tgt_db_inst, 'instance_fault_create')
        self.tgt_db_inst.instance_fault_create(self.ctxt,
                                               expected_instance_fault)
        self.mox.ReplayAll()

        self.src_msg_runner.instance_fault_create_at_top(self.ctxt,
                fake_instance_fault)

    def test_bw_usage_update_at_top(self):
        fake_bw_update_info = {'uuid': 'fake_uuid',
                               'mac': 'fake_mac',
                               'start_period': 'fake_start_period',
                               'bw_in': 'fake_bw_in',
                               'bw_out': 'fake_bw_out',
                               'last_ctr_in': 'fake_last_ctr_in',
                               'last_ctr_out': 'fake_last_ctr_out',
                               'last_refreshed': 'fake_last_refreshed'}

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst, 'bw_usage_update')
        self.mox.StubOutWithMock(self.mid_db_inst, 'bw_usage_update')

        self.mox.StubOutWithMock(self.tgt_db_inst, 'bw_usage_update')
        self.tgt_db_inst.bw_usage_update(self.ctxt, **fake_bw_update_info)

        self.mox.ReplayAll()

        self.src_msg_runner.bw_usage_update_at_top(self.ctxt,
                                                   fake_bw_update_info)

    def test_sync_instances(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        project_id = 'fake_project_id'
        updated_since_raw = 'fake_updated_since_raw'
        updated_since_parsed = 'fake_updated_since_parsed'
        deleted = 'fake_deleted'

        instance1 = dict(uuid='fake_uuid1', deleted=False)
        instance2 = dict(uuid='fake_uuid2', deleted=True)
        fake_instances = [instance1, instance2]

        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_update_at_top')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_destroy_at_top')

        self.mox.StubOutWithMock(timeutils, 'parse_isotime')
        self.mox.StubOutWithMock(cells_utils, 'get_instances_to_sync')

        # Middle cell.
        timeutils.parse_isotime(updated_since_raw).AndReturn(
                updated_since_parsed)
        cells_utils.get_instances_to_sync(self.ctxt,
                updated_since=updated_since_parsed,
                project_id=project_id,
                deleted=deleted).AndReturn([])

        # Bottom/Target cell
        timeutils.parse_isotime(updated_since_raw).AndReturn(
                updated_since_parsed)
        cells_utils.get_instances_to_sync(self.ctxt,
                updated_since=updated_since_parsed,
                project_id=project_id,
                deleted=deleted).AndReturn(fake_instances)
        self.tgt_msg_runner.instance_update_at_top(self.ctxt, instance1)
        self.tgt_msg_runner.instance_destroy_at_top(self.ctxt, instance2)

        self.mox.ReplayAll()

        self.src_msg_runner.sync_instances(self.ctxt,
                project_id, updated_since_raw, deleted)

    def test_service_get_all_with_disabled(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst, 'service_get_all')
        self.mox.StubOutWithMock(self.mid_db_inst, 'service_get_all')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'service_get_all')

        self.src_db_inst.service_get_all(ctxt,
                disabled=None).AndReturn([1, 2])
        self.mid_db_inst.service_get_all(ctxt,
                disabled=None).AndReturn([3])
        self.tgt_db_inst.service_get_all(ctxt,
                disabled=None).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.service_get_all(ctxt,
                                                        filters={})
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_service_get_all_without_disabled(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        disabled = False
        filters = {'disabled': disabled}

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst, 'service_get_all')
        self.mox.StubOutWithMock(self.mid_db_inst, 'service_get_all')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'service_get_all')

        self.src_db_inst.service_get_all(ctxt,
                disabled=disabled).AndReturn([1, 2])
        self.mid_db_inst.service_get_all(ctxt,
                disabled=disabled).AndReturn([3])
        self.tgt_db_inst.service_get_all(ctxt,
                disabled=disabled).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.service_get_all(ctxt,
                                                        filters=filters)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_task_log_get_all_broadcast(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        task_name = 'fake_task_name'
        begin = 'fake_begin'
        end = 'fake_end'
        host = 'fake_host'
        state = 'fake_state'

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst, 'task_log_get_all')
        self.mox.StubOutWithMock(self.mid_db_inst, 'task_log_get_all')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'task_log_get_all')

        self.src_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([1, 2])
        self.mid_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([3])
        self.tgt_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.task_log_get_all(ctxt, None,
                task_name, begin, end, host=host, state=state)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_get_all(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst, 'compute_node_get_all')
        self.mox.StubOutWithMock(self.mid_db_inst, 'compute_node_get_all')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'compute_node_get_all')

        self.src_db_inst.compute_node_get_all(ctxt).AndReturn([1, 2])
        self.mid_db_inst.compute_node_get_all(ctxt).AndReturn([3])
        self.tgt_db_inst.compute_node_get_all(ctxt).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_get_all(ctxt)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_get_all_with_hyp_match(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        hypervisor_match = 'meow'

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst,
                                 'compute_node_search_by_hypervisor')
        self.mox.StubOutWithMock(self.mid_db_inst,
                                 'compute_node_search_by_hypervisor')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'compute_node_search_by_hypervisor')

        self.src_db_inst.compute_node_search_by_hypervisor(ctxt,
                hypervisor_match).AndReturn([1, 2])
        self.mid_db_inst.compute_node_search_by_hypervisor(ctxt,
                hypervisor_match).AndReturn([3])
        self.tgt_db_inst.compute_node_search_by_hypervisor(ctxt,
                hypervisor_match).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_get_all(ctxt,
                hypervisor_match=hypervisor_match)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_stats(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst,
                                 'compute_node_statistics')
        self.mox.StubOutWithMock(self.mid_db_inst,
                                 'compute_node_statistics')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'compute_node_statistics')

        self.src_db_inst.compute_node_statistics(ctxt).AndReturn([1, 2])
        self.mid_db_inst.compute_node_statistics(ctxt).AndReturn([3])
        self.tgt_db_inst.compute_node_statistics(ctxt).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_stats(ctxt)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)
