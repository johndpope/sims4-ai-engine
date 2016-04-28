from sims4.tuning.tunable import Tunable, TunableList, TunableSingletonFactory, TunableTuple
import sims4.geometry
import sims4.math

class TunableDistanceSquared(Tunable):
    __qualname__ = 'TunableDistanceSquared'

    def __init__(self, default, **kwargs):
        super().__init__(float, default, **kwargs)
        self.cache_key = 'TunableDistanceSquared'

    def _convert_to_value(self, content):
        if content is None:
            return
        value = self._type(content)
        return value*value

class TunableVector3(TunableSingletonFactory):
    __qualname__ = 'TunableVector3'
    FACTORY_TYPE = sims4.math.Vector3
    DEFAULT_ZERO = sims4.math.Vector3(0, 0, 0)
    DEFAULT_UNIT = sims4.math.Vector3(1, 1, 1)

    def __init__(self, default, **kwargs):
        super().__init__(x=Tunable(float, default.x, description='x component'), y=Tunable(float, default.y, description='y component'), z=Tunable(float, default.z, description='z component'), **kwargs)
        if default.x == 0 and default.y == 0 and default.z == 0:
            self._default = TunableVector3.DEFAULT_ZERO
        elif default.x == 1 and default.y == 1 and default.z == 1:
            self._default = TunableVector3.DEFAULT_UNIT
        else:
            self._default = sims4.math.Vector3(default.x, default.y, default.z)

class TunableVector2(TunableSingletonFactory):
    __qualname__ = 'TunableVector2'
    FACTORY_TYPE = sims4.math.Vector2
    DEFAULT_ZERO = sims4.math.Vector2(0, 0)
    DEFAULT_UNIT = sims4.math.Vector2(1, 1)

    def __init__(self, default, x_axis_name=None, y_axis_name=None, **kwargs):
        x_axis_name = 'x: ' + x_axis_name if x_axis_name is not None else None
        y_axis_name = 'y: ' + y_axis_name if y_axis_name is not None else None
        super().__init__(x=Tunable(float, default.x, display_name=x_axis_name, description='x component'), y=Tunable(float, default.y, display_name=y_axis_name, description='y component'), **kwargs)
        if default.x == 0 and default.y == 0:
            self._default = TunableVector2.DEFAULT_ZERO
        elif default.x == 1 and default.y == 1:
            self._default = TunableVector2.DEFAULT_UNIT
        else:
            self._default = sims4.math.Vector2(default.x, default.y)

class TunablePolygon(TunableList):
    __qualname__ = 'TunablePolygon'

    def __init__(self, **kwargs):
        vertex_type = TunableVector3(sims4.math.Vector3.ZERO(), description='Polygon vertex')
        super().__init__(vertex_type, **kwargs)
        self._default = None
        self.cache_key = '{}_{}'.format('TunablePolygon', vertex_type.cache_key)

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        constructed_value = sims4.geometry.Polygon(value)
        return constructed_value

class BaseTunableCurve(TunableList):
    __qualname__ = 'BaseTunableCurve'

    def __init__(self, x_axis_name=None, y_axis_name=None, **kwargs):
        super().__init__(TunableVector2(sims4.math.Vector2(0, 0), x_axis_name=x_axis_name, y_axis_name=y_axis_name, description='Point on a Curve'), **kwargs)
        self._default = None

    def _generate_point_list(self, value):
        point_list = []
        if value:
            point_list = [(point.x, point.y) for point in value]
        if not point_list:
            point_list.append((0, 0))
        return point_list

    def invoke_callback(self, instance_class, tunable_name, source, value):
        if self.callback is not None:
            self.callback(instance_class, tunable_name, source, value)

    def invoke_verify_tunable_callback(self, instance_class, tunable_name, source, value):
        if self.verify_tunable_callback is not None:
            self.verify_tunable_callback(instance_class, tunable_name, source, value)

class BaseWeightedTunableCurve(TunableTuple):
    __qualname__ = 'BaseWeightedTunableCurve'

    def __init__(self, x_axis_name=None, y_axis_name=None, **kwargs):
        super().__init__(curve_points=TunableList(TunableVector2(sims4.math.Vector2(0, 0), x_axis_name=x_axis_name, y_axis_name=y_axis_name, description='Point on a Curve')), weight=Tunable(float, 1, description='Value the curve is normalized to as the maximum'), max_y=Tunable(float, 0, description='The output will be divided by this value.  If this is 0, the maximum value tuned on the curve will be used.'), **kwargs)
        self._default = None

    def _generate_point_list(self, value):
        point_list = []
        if value:
            point_list = [(point.x, point.y) for point in value]
        if not point_list:
            point_list.append((0, 0))
        return point_list

    def invoke_callback(self, instance_class, tunable_name, source, value):
        if self.callback is not None:
            self.callback(instance_class, tunable_name, source, value)

    def invoke_verify_tunable_callback(self, instance_class, tunable_name, source, value):
        if self.verify_tunable_callback is not None:
            self.verify_tunable_callback(instance_class, tunable_name, source, value)

class TunableCurve(BaseTunableCurve):
    __qualname__ = 'TunableCurve'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_key = '{}_{}'.format('TunableCurve', self._template.cache_key)

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        constructed_value = sims4.math.LinearCurve(self._generate_point_list(value))
        return constructed_value

class TunableWeightedUtilityCurve(BaseTunableCurve):
    __qualname__ = 'TunableWeightedUtilityCurve'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_key = '{}_{}'.format('TunableWeightedUtilityCurve', self._template.cache_key)

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        constructed_value = sims4.math.WeightedUtilityCurve(self._generate_point_list(value))
        return constructed_value

class TunableWeightedUtilityCurveAndWeight(BaseWeightedTunableCurve):
    __qualname__ = 'TunableWeightedUtilityCurveAndWeight'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_key = '{}_{}'.format('TunableWeightedUtilityCurveAndWeight', id(self))

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        constructed_value = sims4.math.WeightedUtilityCurve(self._generate_point_list(value.curve_points), max_y=value.max_y, weight=value.weight)
        return constructed_value

class TunableCircularUtilityCurve(BaseTunableCurve):
    __qualname__ = 'TunableCircularUtilityCurve'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_key = '{}_{}'.format('TunableCircularUtilityCurve', self._template.cache_key)

    def load_etree_node(self, **kwargs):
        value = super().load_etree_node(**kwargs)
        constructed_value = sims4.math.CircularUtilityCurve(self._generate_point_list(value))
        return constructed_value

