import sims4.log
logger = sims4.log.Logger('GSI')

class GsiSchemaVisualizers:
    __qualname__ = 'GsiSchemaVisualizers'
    GRID = 'GridTable'
    BAR = 'BarChart'
    LINE = 'LineGraph'

class GsiFieldVisualizers:
    __qualname__ = 'GsiFieldVisualizers'
    STRING = 'string'
    FLOAT = 'float'
    INT = 'int'
    TIME = 'time'

class GsiSchema:
    __qualname__ = 'GsiSchema'

    class GsiSchemaCheat:
        __qualname__ = 'GsiSchema.GsiSchemaCheat'

        def __init__(self, cheat_string, label=None, dbl_click=None, in_menu=False):
            output = {'url': cheat_string}
            if label:
                output['label'] = label
            if dbl_click:
                output['dblClick'] = dbl_click
            output['inMenu'] = in_menu
            self.output = output
            self.inputs = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def add_static_param(self, value):
            self.output['url'] += ' {}'.format(value)

        def add_token_param(self, token_name, dynamic_token_fn=None):
            self.output['url'] += ' {{{0}}}'.format(token_name)
            if dynamic_token_fn is not None:
                self.output[token_name] = []
                if 'dynamic_token' in self.output:
                    logger.error('The GSI currently does not support multiple dynamic tokens for the same cheat because of the menu.')
                self.output['dynamic_token'] = token_name
                self.output[token_name] = dynamic_token_fn

        def add_input_param(self, label, default=None):
            if self.inputs is None:
                self.inputs = []
                self.output['inputs'] = self.inputs
            token_name = 'inputVal{}'.format(len(self.inputs) + 1)
            self.output['url'] += ' {{{0}}}'.format(token_name)
            input_schema = {'name': token_name, 'label': label}
            if default:
                input_schema['default'] = default
            self.inputs.append(input_schema)

    def __init__(self, label=None, sim_specific=False, auto_refresh=True):
        self.fields = []
        output = {'definition': self.fields}
        if label:
            output['label'] = label
        self._sim_specific = sim_specific
        if sim_specific is True:
            output['sim_specific'] = sim_specific
        output['autoRefresh'] = auto_refresh
        self.output = output
        self.cheats = None
        self.view_cheats = None
        self.associations = None

    def copy(self, new_label):
        new_schema = GsiSchema(sim_specific=self._sim_specific)
        new_schema.output = dict(self.output)
        new_schema.output['label'] = new_label
        if self.cheats is not None:
            new_schema.cheats = list(self.cheats)
            new_schema.output['cheats'] = new_schema.cheats
        if self.view_cheats is not None:
            new_schema.view_cheats = list()
            new_schema.output['viewCheats'] = new_schema.view_cheats
        if self.associations is not None:
            new_schema.associations = list(self.associations)
            new_schema.output['associations'] = new_schema.associations
        return new_schema

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def add_filter(self, filter_name):
        if 'filters' not in self.output:
            self.output['filters'] = []
        self.output['filters'].append(filter_name)

    def add_field(self, name, label=None, visualizer=GsiFieldVisualizers.STRING, unique_field=False, hidden=False, **kwargs):
        field = {'name': name}
        if unique_field:
            if 'unique_field' not in self.output:
                self.output['unique_field'] = name
            else:
                logger.error('You cannot have more then one field marked as unique in a GSI Schema.')
        if label:
            field['label'] = label
        if visualizer:
            if visualizer == GsiFieldVisualizers.TIME:
                visualizer = GsiFieldVisualizers.INT
                field['is_time'] = True
            field['type'] = visualizer
        if hidden is True:
            field['hidden'] = hidden
        field.update(kwargs)
        self.fields.append(field)

    @property
    def is_sim_specific(self):
        return self._sim_specific

    @property
    def is_graph_schema(self):
        return False

    def add_cheat(self, cheat_string, label=None, dbl_click=None):
        new_cheat = self.GsiSchemaCheat(cheat_string, label=label, dbl_click=dbl_click)
        if self.cheats is None:
            self.cheats = []
            self.output['cheats'] = self.cheats
        self.cheats.append(new_cheat.output)
        return new_cheat

    def add_view_cheat(self, cheat_string, label=None, dbl_click=None, in_menu=False):
        new_cheat = self.GsiSchemaCheat(cheat_string, label=label, dbl_click=dbl_click, in_menu=in_menu)
        if self.view_cheats is None:
            self.view_cheats = []
            self.output['viewCheats'] = self.view_cheats
        self.view_cheats.append(new_cheat.output)
        return new_cheat

    def add_has_many(self, name, schema_class, *args, **kwargs):
        new_schema = schema_class(*args, **kwargs)
        if self.associations is None:
            self.associations = []
            self.output['associations'] = self.associations
        self.output['associations'].append({'name': name, 'type': 'hasMany', 'schema': new_schema.output})
        return new_schema

    def add_has_one(self, name, schema_class, *args, **kwargs):
        new_schema = schema_class(*args, **kwargs)
        if self.associations is None:
            self.associations = []
            self.output['associations'] = self.associations
        self.output['associations'].append({'name': name, 'type': 'hasOne', 'schema': new_schema.output})
        return new_schema

class GsiGridSchema(GsiSchema):
    __qualname__ = 'GsiGridSchema'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output['visualizer'] = GsiSchemaVisualizers.GRID

    def add_field(self, *args, width=None, **kwargs):
        if width:
            kwargs['width'] = width
        super().add_field(*args, **kwargs)

class GsiGraphSchema(GsiSchema):
    __qualname__ = 'GsiGraphSchema'

    class Axis:
        __qualname__ = 'GsiGraphSchema.Axis'
        X = 'xField'
        Y = 'yField'

    class AxisType:
        __qualname__ = 'GsiGraphSchema.AxisType'
        Invalid = 'Invalid'
        Numeric = 'Numeric'
        Category = 'Category'

    def __init__(self, *args, x_min=None, x_max=None, y_min=None, y_max=None, x_axis_label='', y_axis_label='', x_axis_type=AxisType.Category, y_axis_type=AxisType.Numeric, has_legend=True, **kwargs):
        super().__init__(*args, **kwargs)
        if x_min is not None:
            self.output['xMin'] = x_min
        if x_max is not None:
            self.output['xMax'] = x_max
        if y_min is not None:
            self.output['yMin'] = y_min
        if y_max is not None:
            self.output['yMax'] = y_max
        self.output['hasLegend'] = has_legend
        self.output['xAxisLabel'] = x_axis_label
        self.output['yAxisLabel'] = y_axis_label
        self.output['xAxisType'] = x_axis_type
        self.output['yAxisType'] = y_axis_type

    def add_field(self, *args, axis=None, is_percent=None, **kwargs):
        if axis:
            kwargs['axis'] = axis
        if is_percent:
            kwargs['is_percent'] = is_percent
        super().add_field(*args, **kwargs)

    @property
    def is_graph_schema(self):
        return True

class GsiBarChartSchema(GsiGraphSchema):
    __qualname__ = 'GsiBarChartSchema'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output['visualizer'] = GsiSchemaVisualizers.BAR

class GsiLineGraphSchema(GsiGraphSchema):
    __qualname__ = 'GsiLineGraphSchema'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output['visualizer'] = GsiSchemaVisualizers.LINE
        self.output['graphType'] = 'line'

class GsiScatterGraphSchema(GsiGraphSchema):
    __qualname__ = 'GsiScatterGraphSchema'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output['visualizer'] = GsiSchemaVisualizers.LINE
        self.output['graphType'] = 'scatter'

class GSIGlobalCheatSchema(GsiSchema):
    __qualname__ = 'GSIGlobalCheatSchema'

    class GsiSchemaCheat(GsiSchema.GsiSchemaCheat):
        __qualname__ = 'GSIGlobalCheatSchema.GsiSchemaCheat'

        def add_token_param(self, token_name):
            raise RuntimeError('Cannot add a token param to a global GSI Cheat')

        def add_input_param(self, label, default=None):
            raise RuntimeError('Cannot add an input param to a global GSI Cheat')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output['is_global_cheat'] = True

    def add_field(self, name, label=None, visualizer=GsiFieldVisualizers.STRING, hidden=False, **kwargs):
        raise RuntimeError('Cannot call add_field on a global GSI Cheat')

    def add_view_cheat(self, cheat_string, label=None):
        raise RuntimeError('Cannot call add_view_cheat on a global GSI Cheat')

    def add_has_many(self, name, schema_class, *args, **kwargs):
        raise RuntimeError('Cannot call add_has_many on a global GSI Cheat')

    def add_has_one(self, name, schema_class, *args, **kwargs):
        raise RuntimeError('Cannot call add_has_one on a global GSI Cheat')

