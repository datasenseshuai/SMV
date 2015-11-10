/*
 * This file is licensed under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.tresamigos.smv {

class SmvLinkFollowTest extends SmvTestUtil {
  override val appArgs = Seq(
    "--smv-props",
    "smv.stages=org.tresamigos.smv.smvLinkTestPkg1:org.tresamigos.smv.smvLinkTestPkg2"
  )++ Seq("-m", "org.tresamigos.smv.smvLinkTestPkg2.T") ++ Seq("--data-dir", testcaseTempDir)

  test("Test SmvModuleLink follow link") {
    val res = app.resolveRDD(smvLinkTestPkg2.T)
  }

}

class SmvLinkFollowWithVersionTest extends SmvTestUtil {
  override val appArgs = Seq(
    "--smv-props",
    "smv.stages=org.tresamigos.smv.smvLinkTestPkg1:org.tresamigos.smv.smvLinkTestPkg2," +
    "smv.stages.smvLinkTestPkg1.version=v1"
  )++ Seq("-m", "org.tresamigos.smv.smvLinkTestPkg2.T") ++ Seq("--data-dir", testcaseTempDir)

  test("Test SmvModuleLink follow link with version config") {
    intercept[org.apache.hadoop.mapred.InvalidInputException]{
      val res = app.resolveRDD(smvLinkTestPkg2.T)
    }
  }

}

} // end: package org.tresamigos.smv

/**
 * packages below are used for testing the modules in package, modules in stage, etc.
 */
package org.tresamigos.smv.smvLinkTestPkg1 {

import org.tresamigos.smv.{SmvOutput, SmvModule}

object Y extends SmvModule("Y Module") with SmvOutput {
  override def requiresDS() = Nil
  override def run(inputs: runParams) = app.createDF("s:String", "a;b;b")
}
}

package org.tresamigos.smv.smvLinkTestPkg2 {

import org.tresamigos.smv.{SmvOutput, SmvModule, SmvModuleLink}

object L extends SmvModuleLink(org.tresamigos.smv.smvLinkTestPkg1.Y)

object T extends SmvModule("T Module") {
  override def requiresDS() = Seq(L)
  override def run(inputs: runParams) = inputs(L)
}

}
