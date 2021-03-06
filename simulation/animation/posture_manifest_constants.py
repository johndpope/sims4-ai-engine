from animation.posture_manifest
import MATCH_ANY, MATCH_NONE, PostureManifestEntry, PostureManifest
from interactions.constraints
import Constraint, create_constraint_set
from postures.posture_state_spec
import create_body_posture_state_spec
STAND_POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, '', 'stand', 'FullBody', MATCH_ANY, MATCH_ANY, MATCH_ANY), PostureManifestEntry(None, '', 'stand', 'UpperBody', MATCH_ANY, MATCH_ANY, MATCH_ANY))).intern()
STAND_NO_SURFACE_POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, '', 'stand', 'FullBody', MATCH_ANY, MATCH_ANY, MATCH_NONE), PostureManifestEntry(None, '', 'stand', 'UpperBody', MATCH_ANY, MATCH_ANY, MATCH_NONE))).intern()
STAND_NO_CARRY_NO_SURFACE_POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, '', 'stand', 'FullBody', MATCH_NONE, MATCH_NONE, MATCH_NONE), PostureManifestEntry(None, '', 'stand', 'UpperBody', MATCH_NONE, MATCH_NONE, MATCH_NONE))).intern()
STAND_POSTURE_STATE_SPEC = create_body_posture_state_spec(STAND_POSTURE_MANIFEST)
STAND_NO_SURFACE_STATE_SPEC = create_body_posture_state_spec(STAND_NO_SURFACE_POSTURE_MANIFEST)
STAND_NO_CARRY_NO_SURFACE_STATE_SPEC = create_body_posture_state_spec(STAND_NO_CARRY_NO_SURFACE_POSTURE_MANIFEST)
STAND_CONSTRAINT = Constraint(debug_name = 'Stand', posture_state_spec = STAND_POSTURE_STATE_SPEC)
STAND_NO_SURFACE_CONSTRAINT = Constraint(debug_name = 'Stand-NoSurface', posture_state_spec = STAND_NO_SURFACE_STATE_SPEC)
STAND_NO_CARRY_NO_SURFACE_CONSTRAINT = Constraint(debug_name = 'Stand-NoCarryNoSurface', posture_state_spec = STAND_NO_CARRY_NO_SURFACE_STATE_SPEC)
STAND_CONSTRAINT_OUTER_PENALTY = Constraint(debug_name = 'Stand', posture_state_spec = STAND_POSTURE_STATE_SPEC, ignore_outer_penalty_threshold = 1.0)
STAND_AT_NONE_POSTURE_STATE_SPEC = create_body_posture_state_spec(STAND_POSTURE_MANIFEST, body_target = None)
STAND_AT_NONE_CONSTRAINT = Constraint(debug_name = 'Stand@None', posture_state_spec = STAND_AT_NONE_POSTURE_STATE_SPEC)
SIT_POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, '', 'sit', 'FullBody', MATCH_ANY, MATCH_ANY, MATCH_ANY), PostureManifestEntry(None, '', 'sit', 'UpperBody', MATCH_ANY, MATCH_ANY, MATCH_ANY))).intern()
SIT_NO_CARRY_NO_SURFACE_MANIFEST = PostureManifest((PostureManifestEntry(None, '', 'sit', 'FullBody', MATCH_NONE, MATCH_NONE, MATCH_NONE), PostureManifestEntry(None, '', 'sit', 'UpperBody', MATCH_NONE, MATCH_NONE, MATCH_NONE))).intern()
SIT_POSTURE_STATE_SPEC = create_body_posture_state_spec(SIT_POSTURE_MANIFEST)
SIT_NO_CARRY_NO_SURFACE_STATE_SPEC = create_body_posture_state_spec(SIT_NO_CARRY_NO_SURFACE_MANIFEST)
SIT_CONSTRAINT = Constraint(debug_name = 'Sit', posture_state_spec = SIT_POSTURE_STATE_SPEC)
SIT_NO_CARRY_NO_SURFACE_CONSTRAINT = Constraint(debug_name = 'SitNoCarryNoSurface', posture_state_spec = SIT_NO_CARRY_NO_SURFACE_STATE_SPEC)
SIT_INTIMATE_POSTURE_MANIFEST = PostureManifest((PostureManifestEntry(None, 'sitIntimate', '', 'FullBody', MATCH_NONE, MATCH_NONE, MATCH_NONE), PostureManifestEntry(None, 'sitIntimate', '', 'UpperBody', MATCH_NONE, MATCH_NONE, MATCH_NONE))).intern()
SIT_INTIMATE_POSTURE_STATE_SPEC = create_body_posture_state_spec(SIT_INTIMATE_POSTURE_MANIFEST)
SIT_INTIMATE_CONSTRAINT = Constraint(debug_name = 'SitIntimate', posture_state_spec = SIT_INTIMATE_POSTURE_STATE_SPEC)
STAND_OR_SIT_POSTURE_MANIFEST = PostureManifest(list(STAND_POSTURE_MANIFEST) + list(SIT_POSTURE_MANIFEST)).intern()
STAND_OR_SIT_CONSTRAINT = create_constraint_set((STAND_CONSTRAINT, SIT_CONSTRAINT), debug_name = 'Stand-or-Sit')
STAND_OR_SIT_CONSTRAINT_OUTER_PENALTY = create_constraint_set((STAND_CONSTRAINT_OUTER_PENALTY, SIT_CONSTRAINT), debug_name = 'Stand-or-Sit-Outer-Penalty')