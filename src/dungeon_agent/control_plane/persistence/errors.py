class PersistenceConflictError(RuntimeError):
    pass


class SessionAlreadyExistsError(PersistenceConflictError):
    pass


class SessionRevisionConflictError(PersistenceConflictError):
    pass


class EventSequenceConflictError(PersistenceConflictError):
    pass


class CampaignAlreadyExistsError(PersistenceConflictError):
    pass


class CampaignRevisionConflictError(PersistenceConflictError):
    pass


class CampaignEventSequenceConflictError(PersistenceConflictError):
    pass
