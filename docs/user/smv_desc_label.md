# SmvDesc and SmvLabel

**These features are currently only available in Scala SMV**

Both `SmvDesc` and `SmvLabel` are `metadata` components of `DataFrame`'s schema and with a
group of helper methods for user convenience. However they are designed to support different
use cases.

## SmvDesc - Column Description

Sometimes to clearly describe a column with a single column name is very challenging.
Either the name becomes too long or the meaning are ambiguous, or both. There is a
need to add an optional description which can be persisted and printed.

`SmvDesc` is designed for above use case. It has the following features:
* Each column can have 1 and only 1 description, `SmvDesc`, as a `String`
* Adding new description will overwrite old one
* Empty string description is equivalent to no description

### SmvDesc DataFrame Helper Methods
* `smvDesc` - add Descriptions to columns through code
* `smvDescFromDF` - add Descriptions to columns through another DF
* `smvGetDesc` - get Description for a given column or all the name-description pairs
* `smvRemoveDesc` - remove descriptions from a specified column or all columns
* `printDesc` - print schema with descriptions on screen

### Example code
```scala
scala> val res = df.smvDesc("phy_id" -> "Physician ID from CMS")
scala> res.printDesc
a:
b:
c:
phy_id: Physician ID from CMS

scala> descriptionDF.show
+---------+---------------------+
|variables|descriptions         |
+---------+---------------------+
|phy_id   |Physician ID from CMS|
+---------+---------------------+
scala> val res2 = df.smvDescFromDF(descriptionDF)
scala> res2.printDesc
a     :
b     :
c     :
phy_id: Physician ID from CMS
```

## SmvLabel - Column Labels (or Tags)

Analytics work typically work on wide tables. In that scenario, grouping the columns
with labels (or tags) will be very helpful.

`SmvLabel` is designed for above use case. It has the following features:
* Each column can have a Set of labels, `SmvLabel`, as a `Seq[String]`
* Adding new labels will add into the existing Set
* Adding the same label which already exist in the current label set has no impact
* Empty set label is equivalent to unset `SmvLabel`

### SmvLabel DataFrame Helper Methods
* `smvLabel` - add labels to columns
* `smvGetLabels` - get labels from a give column
* `smvRemoveLabel` - remove label values from give columns
* `smvWithLabel` - return column names which has the given label
* `selectByLabel` - do DF projection on columns which has the given label

### Example code
```scala
val df1 = df.smvLabel("name", "sex")("red", "yellow").smvLabel("sex")("green")
val df2 = df1.smvRemoveLabel("sex")("red")
val res = df2.smvGetLabels("sex")  // Seq("yellow", "green")
```

## Persisted SmvModule with Metadata

When the output of an SmvModule has descriptions and/or labels, they will be persisted in the
schema file. As the following,
```
a: String
b: Integer
c: String
phy_id: String @metadata={"smvDesc":"Physician ID from CMS","smvLabel":["id"]}
```

When the persisted data read back in, the descriptions and labels are still there.

## Metadata Propagation

Most DataFrame operations do not support metadata propagation, since there is not
general logic of doing so. From implementation angle, since the metadata is stored in the
schema (as part of the DataFrame) instead of the `Column` objects, almost all column methods and
functions can't propagate metadata. The only exception is `as` method, the following
example demonstrates it:

```scala
scala> val df = app.createDF("a:String", "a")
scala> val df1 = df.smvDesc("a" -> "test col a")
scala> df1.select($"a" as "b").printDesc
b:

scala> df1.select(df1("a") as "b").printDesc
b: test col a

```

As you can see, rename will persist the metadata when you referring the original
column as `df(colname)` instead of `$"colname"`.

Regular projections without re-calculation will preserve metadata.
