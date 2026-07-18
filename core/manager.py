class ModuleManager:

    def __init__(self):

        self.modules = {}

    #####################################

    def register(self, key, module):

        self.modules[key] = module

    #####################################

    def get(self, name):

        return self.modules.get(name)

    #####################################

    def sync_all(self):

        for module in self.modules.values():

            print(f"Syncing {module.name}")

            module.sync()

    #####################################

    def reports(self):

        for module in self.modules.values():

            module.report()