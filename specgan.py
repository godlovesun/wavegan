import tensorflow as tf


def conv2d_transpose(
    inputs,
    filters,
    kernel_len,
    stride=2,
    padding='same',
    upsample='zeros'):
  if upsample == 'zeros':
    return tf.layers.conv2d_transpose(
        inputs,
        filters,
        kernel_len,
        strides=(stride, stride),
        padding='same')
  elif upsample in ['nn', 'linear', 'cubic']:
    batch_size = tf.shape(inputs)[0]
    _, h, w, nch = inputs.get_shape().as_list()

    x = inputs

    if upsample == 'nn':
      upsampler = tf.image.resize_nearest_neighbor
    elif upsample == 'linear':
      upsampler = tf.image.resize_bilinear
    else:
      upsampler = tf.image.resize_bicubic

    x = upsampler(x, [h * stride, w * stride])
    
    return tf.layers.conv2d(
        x,
        filters,
        kernel_len,
        strides=(1, 1),
        padding='same')
  else:
    raise NotImplementedError


"""
  Input: [None, in_dim], in_dim = z_dim + dynamic_c_dim + static_c_dim
  Output: [None, 128, 128, 1]
"""
def SpecGANGenerator(
    z,
    kernel_len=5,
    dim=64,
    out_static_dim=20,
    use_batchnorm=False,
    upsample='zeros',
    train=False):
  batch_size = tf.shape(z)[0]

  if use_batchnorm:
    batchnorm = lambda x: tf.layers.batch_normalization(x, training=train)
  else:
    batchnorm = lambda x: x

  # FC and reshape for convolution
  # [in_dim] -> [4, 4, 1024]
  output = z
  with tf.variable_scope('z_project'):
    output = tf.layers.dense(output, 4 * 4 * dim * 16)
    output = tf.reshape(output, [batch_size, 4, 4, dim * 16])
    output = batchnorm(output)
  output = tf.nn.relu(output)

  # Layer 0
  # [4, 4, 1024] -> [8, 8, 512]
  with tf.variable_scope('upconv_0'):
    output = conv2d_transpose(output, dim * 8, kernel_len, 2, upsample=upsample)
    output = batchnorm(output)
  output = tf.nn.relu(output)

  # Layer 1
  # [8, 8, 512] -> [16, 16, 256]
  with tf.variable_scope('upconv_1'):
    output = conv2d_transpose(output, dim * 4, kernel_len, 2, upsample=upsample)
    output = batchnorm(output)
  output = tf.nn.relu(output)

  # Static branch
  # [16, 16, 256] -> [out_static_dim]
  with tf.variable_scope('static_dense'):
    # Flatten
    static_out = tf.reshape(output, [batch_size, 16 * 16 * 256])
    static_out = tf.layers.dense(static_out, out_static_dim)
    static_out = tf.nn.tanh(static_out)

  # Dynamic branch
  # Layer 2
  # [16, 16, 256] -> [32, 32, 128]
  with tf.variable_scope('upconv_2'):
    output = conv2d_transpose(output, dim * 2, kernel_len, 2, upsample=upsample)
    output = batchnorm(output)
  output = tf.nn.relu(output)

  # Layer 3
  # [32, 32, 128] -> [64, 64, 64]
  with tf.variable_scope('upconv_3'):
    output = conv2d_transpose(output, dim, kernel_len, 2, upsample=upsample)
    output = batchnorm(output)
  output = tf.nn.relu(output)

  # Layer 4
  # [64, 64, 64] -> [128, 128, 1]
  with tf.variable_scope('upconv_4'):
    output = conv2d_transpose(output, 1, kernel_len, 2, upsample=upsample)
  output = tf.nn.tanh(output)

  # Automatically update batchnorm moving averages every time G is used during training
  if train and use_batchnorm:
    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
    if len(update_ops) != 10:
      raise Exception('Other update ops found in graph')
    with tf.control_dependencies(update_ops):
      output = tf.identity(output)

  return output, static_out


def lrelu(inputs, alpha=0.2):
  return tf.maximum(alpha * inputs, inputs)


"""
  Input: [None, 128, 128, 1]
  Output: [None, out_dim=100] output
"""
def SpecGANEncoder(
    x,
    kernel_len=5,
    dim=64,
    out_dim=100,
    use_batchnorm=False):
  batch_size = tf.shape(x)[0]

  if use_batchnorm:
    batchnorm = lambda x: tf.layers.batch_normalization(x, training=True)
  else:
    batchnorm = lambda x: x

  # Layer 0
  # [128, 128, 1] -> [64, 64, 64]
  output = x
  with tf.variable_scope('downconv_0'):
    output = tf.layers.conv2d(output, dim, kernel_len, 2, padding='SAME')
  output = lrelu(output)

  # Layer 1
  # [64, 64, 64] -> [32, 32, 128]
  with tf.variable_scope('downconv_1'):
    output = tf.layers.conv2d(output, dim * 2, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 2
  # [32, 32, 128] -> [16, 16, 256]
  with tf.variable_scope('downconv_2'):
    output = tf.layers.conv2d(output, dim * 4, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 3
  # [16, 16, 256] -> [8, 8, 512]
  with tf.variable_scope('downconv_3'):
    output = tf.layers.conv2d(output, dim * 8, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 4
  # [8, 8, 512] -> [4, 4, 1024]
  with tf.variable_scope('downconv_4'):
    output = tf.layers.conv2d(output, dim * 16, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Flatten
  output = tf.reshape(output, [batch_size, 4 * 4 * dim * 16])

  # Connect to single logit
  with tf.variable_scope('output'):
    output = tf.layers.dense(output, out_dim)

  # Don't need to aggregate batchnorm update ops like we do for the generator because we only use the discriminator for training

  return output

"""
  Input: 
    dynamic_x: [None, 128, 128, 1]
    static_x: [None, static_tract_dim=20]
  Output: [None] (linear) output
"""
def SpecGANDiscriminator(
    dynamic_x,
    static_x,
    dynamic_c,
    static_c,
    kernel_len=5,
    dim=64,
    dynamic_out_dim = 100,
    static_out_dim = 50,
    use_batchnorm=False):
  batch_size = tf.shape(x)[0]

  if use_batchnorm:
    batchnorm = lambda x: tf.layers.batch_normalization(x, training=True)
  else:
    batchnorm = lambda x: x

  # Layer 0
  # [128, 128, 1] -> [64, 64, 64]
  output = dynamic_x
  with tf.variable_scope('downconv_0'):
    output = tf.layers.conv2d(output, dim, kernel_len, 2, padding='SAME')
  output = lrelu(output)

  # Layer 1
  # [64, 64, 64] -> [32, 32, 128]
  with tf.variable_scope('downconv_1'):
    output = tf.layers.conv2d(output, dim * 2, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 2
  # [32, 32, 128] -> [16, 16, 256]
  with tf.variable_scope('downconv_2'):
    output = tf.layers.conv2d(output, dim * 4, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 3
  # [16, 16, 256] -> [8, 8, 512]
  with tf.variable_scope('downconv_3'):
    output = tf.layers.conv2d(output, dim * 8, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Layer 4
  # [8, 8, 512] -> [4, 4, 1024]
  with tf.variable_scope('downconv_4'):
    output = tf.layers.conv2d(output, dim * 16, kernel_len, 2, padding='SAME')
    output = batchnorm(output)
  output = lrelu(output)

  # Flatten
  output = tf.reshape(output, [batch_size, 4 * 4 * dim * 16])

  # Connect to single logit
  with tf.variable_scope('dynamic_out'):
    output = tf.layers.dense(output, dynamic_out_dim)

  # Static input transform
  # [static_tract_dim] ->  [static_out_dim]
  with tf.variable_scope('static_out'):
    static_out = tf.layers.dense(static_x, static_out_dim)

  # Concate dynamic, static information, dynamic_c, static_c information
  with tf.variable_scope('output'):
    all_output = tf.concat([output, static_out, dynamic_c, static_c], 1)
    all_output = tf.layers.dense(all_output, 1)[:, 0]

  # Don't need to aggregate batchnorm update ops like we do for the generator because we only use the discriminator for training

  return all_output
