from event_testing.tests import TunableTestVariant
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, TunableList, TunableTuple, Tunable
import services
import sims4.log
logger = sims4.log.Logger('Test Based Score')

class TestBasedScore(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.test_based_score_manager()):
    __qualname__ = 'TestBasedScore'

    @classmethod
    def _verify_tuning_callback(cls):
        for score in cls._scores:
            while score.test is None:
                logger.error('Invalid tuning. Test in test based score ({}) is tuned to None. Please set a valid test!', cls, owner='rfleig')

    INSTANCE_TUNABLES = {'_scores': TunableList(TunableTuple(test=TunableTestVariant(description='\n                        Pass this test to get the accompanied score.'), score=Tunable(float, 1, description='\n                        Score you get for passing the test.')), description='\n                    A list of tuned tests and accompanied scores. All successful\n                    tests add the scores to an effective score. The effective \n                    score is used by threshold tests.')}

    @classmethod
    def get_score(cls, resolver):
        yield_to_irq()
        return sum(test_pair.score for test_pair in cls._scores if resolver(test_pair.test))

    @classmethod
    def debug_dump(cls, resolver, dump=logger.warn):
        dump('Generating scores for {}'.format(cls.__name__))
        for test_pair in cls._scores:
            dump('    Testing {}'.format(type(test_pair.test).__name__))
            result = resolver(test_pair.test)
            if result:
                dump('        PASS: +{}'.format(test_pair.score))
            else:
                dump('        FAILED: {}'.format(result))
        dump('  Score: {}'.format(cls.get_score(resolver)))

