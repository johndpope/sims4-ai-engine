from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiFieldVisualizers, GsiLineGraphSchema, GsiScatterGraphSchema
import services
import sims4
logger = sims4.log.Logger('GSI Test Handlers')
test_graph_schema_1 = GsiLineGraphSchema(label='TestViews/TestLineGraph', x_axis_label='X-Axis', y_axis_label='Y-Axis')
test_graph_schema_1.add_field('name', axis=GsiLineGraphSchema.Axis.X)
test_graph_schema_1.add_field('value', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
test_graph_schema_1.add_field('focus_score', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)
test_graph_schema_1.add_field('x_pos', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)

@GsiHandler('test_1_graph', test_graph_schema_1)
def generate_test_1_graph_data(sim_id:int=None):
    all_objects = list(services.object_manager().values())
    graph_data = []
    for cur_obj in all_objects:
        if cur_obj.is_sim:
            pass
        graph_entry = {'name': str(cur_obj), 'value': cur_obj.current_value, 'focus_score': cur_obj._focus_score, 'x_pos': cur_obj.position.x}
        graph_data.append(graph_entry)
    return graph_data

test_graph_schema_2 = GsiScatterGraphSchema(label='TestViews/TestScatterGraph', x_axis_label='X-Axis', y_axis_label='Y-Axis', x_axis_type=GsiScatterGraphSchema.AxisType.Numeric, y_axis_type=GsiScatterGraphSchema.AxisType.Numeric, has_legend=False)
test_graph_schema_2.add_field('xPos', axis=GsiLineGraphSchema.Axis.X, type=GsiFieldVisualizers.FLOAT)
test_graph_schema_2.add_field('zPos', axis=GsiLineGraphSchema.Axis.Y, type=GsiFieldVisualizers.FLOAT)

@GsiHandler('test_2_graph', test_graph_schema_2)
def generate_test_2_graph_data(sim_id:int=None):
    all_objects = list(services.object_manager().values())
    graph_data = []
    for cur_obj in all_objects:
        if cur_obj.footprint_polygon is not None:
            for point in cur_obj.footprint_polygon:
                graph_data.append({'xPos': point.z, 'zPos': point.x})
        else:
            graph_data.append({'xPos': cur_obj.position.z, 'zPos': cur_obj.position.x})
    return graph_data

