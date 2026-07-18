class Registry:

    def __init__(self):

        self.models = {}

        self.modules = {}

    ###############################

    def register_model(self, model):

        self.models[model.__name__] = model

    ###############################

    def register_module(self, module):

        self.modules[module.name] = module