from drivers.chroma6312 import Chroma6312
from drivers.prodigit3311f import Prodigit3311F


class LoadFactory:

    @staticmethod
    def create(model,
               connection_type,
               address):

        if model == "6312A":
            return Chroma6312(
                connection_type,
                address
            )

        elif model == "3311F":
            return Prodigit3311F(
                connection_type,
                address
            )

        else:
            raise ValueError(
                f"Unsupported model: {model}"
            )