# This file is licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""SMV DataSet Framework interface

This module defines the abstract classes which formed the SmvDataSet Framework for clients' projects
"""

from pyspark import SparkContext
from pyspark.sql import HiveContext, DataFrame
from pyspark.sql.column import Column
from pyspark.sql.functions import col
from utils import smv_copy_array
from stacktrace_mixin import WithStackTrace, with_stacktrace

import abc

import inspect
import sys
import traceback

from dqm import SmvDQM
from error import SmvRuntimeError

if sys.version >= '3':
    basestring = unicode = str
    long = int
    from io import StringIO
    from importlib import reload
else:
    from cStringIO import StringIO

def _disassemble(obj):
    """Disassembles a module and returns bytecode as a string.
    """
    mod = obj if (isinstance(obj, type)) else obj.__class__

    buf = StringIO()
    import dis
    if sys.version >= '3':
        dis.dis(mod, file=buf)
    else:
        stdout = sys.stdout
        sys.stdout = buf
        dis.dis(mod)
        sys.stdout = stdout
    ret = buf.getvalue()
    buf.close()
    return ret

def _smvhash(text):
    """Python's hash function will return different numbers from run to
    from, starting from 3.  Provide a deterministic hash function for
    use to calculate sourceCodeHash.
    """
    import binascii
    return binascii.crc32(text)

def _stripComments(code):
    import re
    code = str(code)
    return re.sub(r'(?m)^ *(#.*\n?|[ \t]*\n)', '', code)

class SmvOutput(object):
    """Mixin which marks an SmvModule as one of the output of its stage

        SmvOutputs are distinct from other SmvDataSets in that
            * SmvModuleLinks can *only* link to SmvOutputs
            * The -s and --run-app options of smv-pyrun only run SmvOutputs and their dependencies.
    """
    IsSmvOutput = True

    def tableName(self):
        """The user-specified table name used when exporting data to Hive (optional)

            Returns:
                (string)
        """
        return None

class SmvDataSet(WithStackTrace):
    """Abstract base class for all SmvDataSets
    """

    # Python's issubclass() check does not work well with dynamically
    # loaded modules.  In addition, there are some issues with the
    # check, when the `abc` module is used as a metaclass, that we
    # don't yet quite understand.  So for a workaround we add the
    # typcheck in the Smv hierarchies themselves.
    IsSmvDataSet = True

    __metaclass__ = abc.ABCMeta

    def __init__(self, smvApp):
        self.smvApp = smvApp

    def description(self):
        return self.__doc__

    @abc.abstractmethod
    def requiresDS(self):
        """User-specified list of dependencies

            Override this method to specify the SmvDataSets needed as inputs.

            Returns:
                (list(SmvDataSet)): a list of dependencies
        """

    def dqm(self):
        """DQM policy

            Override this method to define your own DQM policy (optional).
            Default is an empty policy.

            Returns:
                (SmvDQM): a DQM policy
        """
        return SmvDQM()

    @abc.abstractmethod
    def doRun(self, validator, known):
        """Comput this dataset, and return the dataframe"""

    def version(self):
        """Version number

            Each SmvDataSet is versioned with a numeric string, so it and its result
            can be tracked together.

            Returns:
                (str): version number of this SmvDataSet
        """
        return "0";

    def isOutput(self):
        return isinstance(self, SmvOutput)

    # Note that the Scala SmvDataSet will combine sourceCodeHash and instanceValHash
    # to compute datasetHash
    def sourceCodeHash(self):
        """Hash computed based on the source code of the dataset's class
        """
        try:
            cls = self.__class__
            try:
                src = inspect.getsource(cls)
                src_no_comm = _stripComments(src)
                # DO NOT use the compiled byte code for the hash computation as
                # it doesn't change when constant values are changed.  For example,
                # "a = 5" and "a = 6" compile to same byte code.
                # co_code = compile(src, inspect.getsourcefile(cls), 'exec').co_code
                res = _smvhash(src_no_comm)
            except Exception as err: # `inspect` will raise error for classes defined in the REPL
                # Instead of handle the case that module defined in REPL, just raise Exception here
                # res = _smvhash(_disassemble(cls))
                traceback.print_exc()
                message = "{0}({1!r})".format(type(err).__name__, err.args)
                raise Exception(message + "\n" + "SmvDataSet " + self.urn() +" defined in shell can't be persisted")

            # include sourceCodeHash of parent classes
            for m in inspect.getmro(cls):
                try:
                    if m.IsSmvDataSet and m != cls and not m.fqn().startswith("smv."):
                        res += m(self.smvApp).sourceCodeHash()
                except: pass

            # if module inherits from SmvRunConfig, then add hash of all config values to module hash
            if hasattr(self, "_smvGetRunConfigHash"):
                res += self._smvGetRunConfigHash()

            # ensure python's numeric type can fit in a java.lang.Integer
            return res & 0x7fffffff
        except BaseException as e:
            traceback.print_exc()
            raise e

    def instanceValHash(self):
        """Hash computed based on instance values of the dataset, such as the timestamp of an input file
        """
        return 0

    @classmethod
    def fqn(cls):
        """Returns the fully qualified name
        """
        return cls.__module__ + "." + cls.__name__

    @classmethod
    def urn(cls):
        return "mod:" + cls.fqn()

    @with_stacktrace
    def isEphemeral(self):
        """Should this SmvDataSet skip persisting its data?

            Returns:
                (bool): True if this SmvDataSet should not persist its data, false otherwise
        """
        return False

    def publishHiveSql(self):
        """An optional sql query to run to publish the results of this module when the
           --publish-hive command line is used.  The DataFrame result of running this
           module will be available to the query as the "dftable" table.

            Example:
                >>> return "insert overwrite table mytable select * from dftable"

            Note:
                If this method is not specified, the default is to just create the table specified by tableName() with the results of the module.

           Returns:
               (string): the query to run.
        """
        return None

    @abc.abstractmethod
    def dsType(self):
        """Return SmvDataSet's type"""

    def dqmWithTypeSpecificPolicy(self):
        try:
            res = self.dqm()
        except BaseException as err:
            traceback.print_exc()
            raise err

        return res

    def dependencies(self):
        # Try/except block is a short-term solution (read: hack) to ensure that
        # the user gets a full stack trace when SmvDataSet user-defined methods
        # causes errors
        try:
            arr = smv_copy_array(self.smvApp.sc, *[x.urn() for x in self.requiresDS()])
        except BaseException as err:
            traceback.print_exc()
            raise err

        return arr

    def getDataFrame(self, validator, known):
        # Try/except block is a short-term solution (read: hack) to ensure that
        # the user gets a full stack trace when SmvDataSet user-defined methods
        # causes errors
        try:
            df = self.doRun(validator, known)
            if not isinstance(df, DataFrame):
                raise SmvRuntimeError(self.fqn() + " produced " + type(df).__name__ + " in place of a DataFrame")
            else:
                jdf = df._jdf
        except BaseException as err:
            traceback.print_exc()
            raise err

        return jdf

    class Java:
        implements = ['org.tresamigos.smv.ISmvModule']

class SmvInput(SmvDataSet):
    """SmvDataSet representing external input
    """

    __metaclass__ = abc.ABCMeta

    def isEphemeral(self):
        return True

    def dsType(self):
        return "Input"

    def requiresDS(self):
        return []

    def run(self, df):
        """Post-processing for input data

            Args:
                df (DataFrame): input data

            Returns:
                (DataFrame): processed data
        """
        return df

    @abc.abstractproperty
    def getRawScalaInputDS(self):
        """derived classes should provide the raw scala proxy input dataset (e.g. SmvCsvFile)
           that is created in their init."""


    def instanceValHash(self):
        # Defer to Scala target for instanceValHash
        return self.getRawScalaInputDS().instanceValHash()

    def doRun(self, validator, known):
        jdf = self.getRawScalaInputDS().doRun(validator)
        return self.run(DataFrame(jdf, self.smvApp.sqlContext))

class WithParser(object):
    """shared parser funcs"""

    def dqmWithTypeSpecificPolicy(self):
        """for parsers we should get the type specific dqm policy from the
           concrete scala proxy class that is the actual input (e.g. SmvCsvFile)"""
        try:
            userDqm = self.dqm()
            scalaInputDS = self.getRawScalaInputDS()
            res = scalaInputDS.dqmWithTypeSpecificPolicy(userDqm)
        except BaseException as err:
            traceback.print_exc()
            raise err

        return res

    def forceParserCheck(self):
        return True

    def failAtParsingError(self):
        return True

    def defaultCsvWithHeader(self):
        return self.smvApp.defaultCsvWithHeader()

    def defaultTsv(self):
        return self.smvApp.defaultTsv()

    def defaultTsvWithHeader(self):
        return self.smvApp.defaultTsvWithHeader()

    def csvAttr(self):
        """Specifies the csv file format.  Corresponds to the CsvAttributes case class in Scala.
        """
        return None

# Note: due to python MRO, WithParser MUST come first in inheritance hierarchy.
# Otherwise we will pick methods up from SmvDataSet instead of WithParser.
class SmvFile(WithParser, SmvInput):
    def userSchema(self):
        """Get user-defined schema

            Override this method to define your own schema for the target file.
            Schema declared in this way take priority over .schema files. Schema
            should be specified in the format "colName1:colType1;colName2:colType2"

            Returns:
                (string):
        """
        return None


class SmvCsvFile(SmvFile):
    """Input from a file in CSV format
    """

    def __init__(self, smvApp):
        super(SmvCsvFile, self).__init__(smvApp)
        self._smvCsvFile = smvApp.j_smvPyClient.smvCsvFile(
            self.fqn(),
            self.path(),
            self.csvAttr(),
            self.forceParserCheck(),
            self.failAtParsingError(),
            smvApp.scalaOption(self.userSchema())
        )


    def getRawScalaInputDS(self):
        return self._smvCsvFile

    def description(self):
        return "Input file: @" + self.path()

    @abc.abstractproperty
    def path(self):
        """User-specified path to the input csv file

            Override this to specify the path to the csv file.

            Returns:
                (str): path
        """

    def doRun(self, validator, known):
        jdf = self._smvCsvFile.doRun(validator)
        return self.run(DataFrame(jdf, self.smvApp.sqlContext))

class SmvMultiCsvFiles(SmvFile):
    """Raw input from multiple csv files sharing single schema

        Instead of a single input file, specify a data dir with files which share
        the same schema.
    """

    def __init__(self, smvApp):
        super(SmvMultiCsvFiles, self).__init__(smvApp)
        self._smvMultiCsvFiles = smvApp._jvm.org.tresamigos.smv.SmvMultiCsvFiles(
            self.dir(),
            self.csvAttr(),
            None,
            smvApp.scalaOption(self.userSchema())
        )

    def userSchema(self):
        return None

    def getRawScalaInputDS(self):
        return self._smvMultiCsvFiles

    def description(self):
        return "Input dir: @" + self.dir()

    @abc.abstractproperty
    def dir(self):
        """Path to the directory containing the csv files and their schema

            Returns:
                (str): path
        """

    def doRun(self, validator, known):
        jdf = self._smvMultiCsvFiles.doRun(validator)
        return self.run(DataFrame(jdf, self.smvApp.sqlContext))

class SmvCsvStringData(SmvInput):
    """Input data defined by a schema string and data string
    """

    def __init__(self, smvApp):
        super(SmvCsvStringData, self).__init__(smvApp)
        self._smvCsvStringData = self.smvApp._jvm.org.tresamigos.smv.SmvCsvStringData(
            self.schemaStr(),
            self.dataStr(),
            False
        )

    def getRawScalaInputDS(self):
        return self._smvCsvStringData

    @abc.abstractproperty
    def schemaStr(self):
        """Smv Schema string.

            E.g. "id:String; dt:Timestamp"

            Returns:
                (str): schema
        """

    @abc.abstractproperty
    def dataStr(self):
        """Smv data string.

            E.g. "212,2016-10-03;119,2015-01-07"

            Returns:
                (str): data
        """

    def doRun(self, validator, known):
        jdf = self._smvCsvStringData.doRun(validator)
        return self.run(DataFrame(jdf, self.smvApp.sqlContext))

class SmvJdbcTable(SmvInput):
    """Input from a table read through JDBC
    """
    def __init__(self, smvApp):
        super(SmvJdbcTable, self).__init__(smvApp)
        self._smvJdbcTable = self.smvApp._jvm.org.tresamigos.smv.SmvJdbcTable(self.tableName())

    def getRawScalaInputDS(self):
        return self._smvJdbcTable

    def description(self):
        return self._smvJdbcTable.description()

    @abc.abstractproperty
    def tableName(self):
        """User-specified name for the table to extract input from

            Override this to specify your own table name.

            Returns:
                (str): table name
        """

    def doRun(self, validator, known):
        jdf = self._smvJdbcTable.doRun(validator)
        return self.run(DataFrame(jdf, self.smvApp.sqlContext))


class SmvHiveTable(SmvInput):
    """Input from a Hive table
    """

    def __init__(self, smvApp):
        super(SmvHiveTable, self).__init__(smvApp)
        self._smvHiveTable = self.smvApp._jvm.org.tresamigos.smv.SmvHiveTable(self.tableName(), self.tableQuery())

    def description(self):
        return "Hive Table: @" + self.tableName()

    def getRawScalaInputDS(self):
        return self._smvHiveTable

    @abc.abstractproperty
    def tableName(self):
        """User-specified name Hive hive table to extract input from

            Override this to specify your own table name.

            Returns:
                (str): table name
        """

    def tableQuery(self):
        """Query used to extract data from Hive table

            Override this to specify your own query (optional). Default is
            equivalent to 'select * from ' + tableName().

            Returns:
                (str): query
        """
        return None

    def doRun(self, validator, known):
        return self.run(DataFrame(self._smvHiveTable.rdd(False), self.smvApp.sqlContext))

class SmvModule(SmvDataSet):
    """Base class for SmvModules written in Python
    """

    IsSmvModule = True


    def dsType(self):
        return "Module"


    class RunParams(object):
        """Map from SmvDataSet to resulting DataFrame

            We need to simulate a dict from ds to df where the same object can be
            keyed by different datasets with the same urn. For example, in the
            module

            class X(SmvModule):
                def requiresDS(self): return [SmvModuleLink("foo")]
                def run(self, i): return i[SmvModuleLink("foo")]

            the i argument of the run method should map SmvModuleLink("foo") to
            the correct DataFrame.

            Args:
                (dict): a map from urn to DataFrame
        """

        def __init__(self, urn2df):
            self.urn2df = urn2df

        def __getitem__(self, ds):
            """Called by the '[]' operator
            """
            return self.urn2df[ds.urn()]

    def __init__(self, smvApp):
        super(SmvModule, self).__init__(smvApp)

    @abc.abstractmethod
    def run(self, i):
        """User-specified definition of the operations of this SmvModule

            Override this method to define the output of this module, given a map
            'i' from inputSmvDataSet to resulting DataFrame. 'i' will have a
            mapping for each SmvDataSet listed in requiresDS. E.g.

            def requiresDS(self):
                return [MyDependency]

            def run(self, i):
                return i[MyDependency].select("importantColumn")

            Args:
                (RunParams): mapping from input SmvDataSet to DataFrame

            Returns:
                (DataFrame): ouput of this SmvModule
        """

    def doRun(self, validator, known):
        urn2df = {}
        for dep in self.requiresDS():
            urn2df[dep.urn()] = DataFrame(known[dep.urn()], self.smvApp.sqlContext)
        i = self.RunParams(urn2df)
        return self.run(i)

class SmvModuleLink(object):
    """A module link provides access to data generated by modules from another stage
    """

    IsSmvModuleLink = True

    def __init__(self, target):
        self.target = target

    def urn(self):
        return 'link:' + self.target.fqn()

class SmvExtDataSet(object):
    """An SmvDataSet representing an external (Scala) SmvDataSet

        E.g. MyExtMod = SmvExtDataSet("the.scala.mod")

        Args:
            fqn (str): fqn of the Scala SmvDataSet

        Returns:
            (SmvExtDataSet): external dataset with given fqn
    """
    def __init__(self, fqn):
        self._fqn = fqn

    def urn(self):
        return 'mod:' + self._fqn

    def fqn(self):
        return self._fqn

def SmvExtModuleLink(refname):
    """Creates a link to an external (Scala) SmvDataSet

        SmvExtModuleLink(fqn) is equivalent to SmvModuleLink(SmvExtDataSet(fqn))

        Args:
            fqn (str): fqn of the the Scala SmvDataSet

        Returns:
            (SmvModuleLink): link to the Scala SmvDataSet
    """
    return SmvModuleLink(SmvExtDataSet(refname))
